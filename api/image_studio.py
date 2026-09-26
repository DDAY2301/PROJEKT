"""Project Image Studio: non-destructive editing, background integration and generation.

Core editing works locally with Pillow. Background removal uses rembg when the
optional package is installed, with a deterministic corner-colour fallback for
simple studio backgrounds. AI background generation can use a local ComfyUI
server; without it, the endpoint produces a brand-aware procedural background so
the feature remains usable offline.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import random
import shutil
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps, ImageDraw

import api.main as core
import api.media as media

COMFYUI_BASE_URL = os.getenv("COMFYUI_BASE_URL", "").strip().rstrip("/")
COMFYUI_CHECKPOINT = os.getenv("COMFYUI_CHECKPOINT", "").strip()
IMAGE_GEN_TIMEOUT = int(os.getenv("IMAGE_GEN_TIMEOUT", "240"))
MAX_BG_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(8 * 1024 * 1024)))


def ensure_schema() -> None:
    media.ensure_media_schema()
    with core.db() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS project_image_history (
              id TEXT PRIMARY KEY,
              image_id TEXT NOT NULL,
              project_id TEXT NOT NULL,
              user_id TEXT NOT NULL,
              original_name TEXT NOT NULL,
              stored_path TEXT NOT NULL,
              repo_path TEXT NOT NULL,
              variants_json TEXT NOT NULL,
              width INTEGER NOT NULL,
              height INTEGER NOT NULL,
              focal_x REAL NOT NULL,
              focal_y REAL NOT NULL,
              kind TEXT NOT NULL,
              placement TEXT NOT NULL,
              alt_text TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )


def _project(project_id: str, user_id: str) -> dict[str, Any]:
    with core.db() as con:
        row = con.execute(
            "SELECT id,config_json FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    return dict(row)


def _image(project_id: str, image_id: str, user_id: str) -> dict[str, Any]:
    ensure_schema()
    with core.db() as con:
        row = con.execute(
            "SELECT * FROM project_images WHERE id=? AND project_id=? AND user_id=?",
            (image_id, project_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Image not found")
    item = dict(row)
    try:
        item["variants"] = json.loads(item.get("variants_json") or "[]")
    except Exception:
        item["variants"] = []
    return item


def _open(path: str) -> Image.Image:
    try:
        opened = Image.open(path)
        opened.load()
    except Exception as exc:
        raise HTTPException(415, "Stored image is not readable") from exc
    image = ImageOps.exif_transpose(opened)
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    return image


def _snapshot(row: dict[str, Any]) -> str:
    snapshot_id = str(uuid.uuid4())
    source = Path(str(row["stored_path"]))
    history_dir = media.UPLOAD_ROOT / str(row["project_id"]) / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    copy_path = history_dir / f"{snapshot_id}-{source.name}"
    shutil.copy2(source, copy_path)
    with core.db() as con:
        con.execute(
            """
            INSERT INTO project_image_history(
              id,image_id,project_id,user_id,original_name,stored_path,repo_path,
              variants_json,width,height,focal_x,focal_y,kind,placement,alt_text,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                snapshot_id,row["id"],row["project_id"],row["user_id"],row["original_name"],
                str(copy_path),row["repo_path"],row.get("variants_json") or "[]",
                int(row.get("width") or 0),int(row.get("height") or 0),
                float(row.get("focal_x") or 50),float(row.get("focal_y") or 50),
                row.get("kind") or "image",row.get("placement") or "auto",
                row.get("alt_text") or "",core.now_iso(),
            ),
        )
    return snapshot_id


def _pct_crop(image: Image.Image, x: float, y: float, w: float, h: float) -> Image.Image:
    vals = [max(0.0, min(100.0, float(v))) for v in (x,y,w,h)]
    x,y,w,h = vals
    if w <= 0 or h <= 0:
        return image.copy()
    left = round(image.width * x / 100)
    top = round(image.height * y / 100)
    right = min(image.width, max(left + 1, round(image.width * min(100, x+w) / 100)))
    bottom = min(image.height, max(top + 1, round(image.height * min(100, y+h) / 100)))
    return image.crop((left, top, right, bottom))


def _remove_background_fallback(image: Image.Image, tolerance: int = 42, feather: int = 8) -> Image.Image:
    rgba = image.convert("RGBA")
    px = rgba.load()
    corners = [
        px[0,0], px[rgba.width-1,0], px[0,rgba.height-1], px[rgba.width-1,rgba.height-1]
    ]
    bg = tuple(sum(c[i] for c in corners)//len(corners) for i in range(3))
    alpha = Image.new("L", rgba.size, 255)
    apx = alpha.load()
    for yy in range(rgba.height):
        for xx in range(rgba.width):
            r,g,b,_ = px[xx,yy]
            distance = math.sqrt((r-bg[0])**2 + (g-bg[1])**2 + (b-bg[2])**2)
            if distance <= tolerance:
                a = 0
            elif distance >= tolerance + 65:
                a = 255
            else:
                a = round((distance-tolerance)/65*255)
            apx[xx,yy] = a
    if feather > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(radius=min(12, feather)))
    rgba.putalpha(alpha)
    return rgba


def _remove_background(image: Image.Image) -> tuple[Image.Image, str]:
    try:
        from rembg import remove  # type: ignore
        raw = io.BytesIO()
        image.convert("RGBA").save(raw, format="PNG")
        result = remove(raw.getvalue())
        out = Image.open(io.BytesIO(result)).convert("RGBA")
        out.load()
        return out, "rembg"
    except Exception:
        return _remove_background_fallback(image), "edge-fallback"


def _cover(image: Image.Image, size: tuple[int,int]) -> Image.Image:
    src = image.convert("RGBA")
    ratio = max(size[0]/src.width, size[1]/src.height)
    target = (max(1, round(src.width*ratio)), max(1, round(src.height*ratio)))
    src = src.resize(target, Image.Resampling.LANCZOS)
    left = max(0, (src.width-size[0])//2)
    top = max(0, (src.height-size[1])//2)
    return src.crop((left,top,left+size[0],top+size[1]))


def _compose(
    subject: Image.Image,
    *,
    mode: str,
    color: str,
    background: Image.Image | None,
    shadow: bool,
) -> Image.Image:
    subject = subject.convert("RGBA")
    size = subject.size
    if mode == "transparent":
        return subject
    if mode == "blur":
        source = background if background is not None else subject
        base = _cover(source, size).convert("RGB").filter(
            ImageFilter.GaussianBlur(radius=max(8, min(size)//28))
        ).convert("RGBA")
    elif mode in {"upload","image"} and background is not None:
        base = _cover(background, size)
    else:
        try:
            rgb = tuple(int(color.lstrip("#")[i:i+2],16) for i in (0,2,4))
        except Exception:
            rgb = (245,247,246)
        base = Image.new("RGBA", size, (*rgb,255))

    if shadow and subject.getchannel("A").getextrema()[0] < 255:
        alpha = subject.getchannel("A")
        shadow_layer = Image.new("RGBA", size, (0,0,0,0))
        shadow_mask = alpha.filter(ImageFilter.GaussianBlur(radius=max(4, min(size)//85)))
        shadow_layer.putalpha(shadow_mask.point(lambda p: int(p*0.24)))
        shifted = ImageChops.offset(shadow_layer, max(3,size[0]//90), max(5,size[1]//65))
        base = Image.alpha_composite(base, shifted)
    return Image.alpha_composite(base, subject)


def _save_result(row: dict[str, Any], image: Image.Image, suffix: str) -> dict[str, Any]:
    project_dir = media.UPLOAD_ROOT / str(row["project_id"])
    project_dir.mkdir(parents=True, exist_ok=True)
    base = f"studio-{media._safe_stem(str(row['original_name']))}-{uuid.uuid4().hex[:8]}-{suffix}"
    placement = str(row.get("placement") or "auto")
    kind = str(row.get("kind") or "image")
    focal_x = float(row.get("focal_x") or 50)
    focal_y = float(row.get("focal_y") or 50)
    variants = media._generate_variants(
        image,
        project_dir,
        base,
        logo=kind == "logo",
        placement=placement,
        focal_x=focal_x,
        focal_y=focal_y,
    )
    webps = [v for v in variants if v["format"] == "webp"]
    primary = max(webps or variants, key=lambda v:int(v["width"]))
    with core.db() as con:
        con.execute(
            """
            UPDATE project_images
            SET stored_path=?,repo_path=?,mime_type='image/webp',variants_json=?,width=?,height=?
            WHERE id=?
            """,
            (
                primary["stored_path"],primary["repo_path"],json.dumps(variants,ensure_ascii=False),
                image.width,image.height,row["id"],
            ),
        )
    return {
        "id": row["id"],
        "repo_path": primary["repo_path"],
        "width": image.width,
        "height": image.height,
        "variants": [media._public_variant(v) for v in variants],
    }


def _project_brand(project: dict[str,Any]) -> tuple[str,str,str]:
    try:
        cfg = json.loads(project.get("config_json") or "{}")
    except Exception:
        cfg = {}
    brand = cfg.get("brand") or {}
    return (
        str(brand.get("primary_color") or "#123f35"),
        str(brand.get("secondary_color") or "#d9ff65"),
        str(brand.get("background_color") or "#f5f7f6"),
    )


def _procedural_background(prompt: str, width: int, height: int, colors: tuple[str,str,str]) -> Image.Image:
    def rgb(value: str, fallback: tuple[int,int,int]) -> tuple[int,int,int]:
        try:
            value=value.lstrip("#")
            return tuple(int(value[i:i+2],16) for i in (0,2,4))
        except Exception:
            return fallback
    c1=rgb(colors[0],(18,63,53)); c2=rgb(colors[1],(217,255,101)); c3=rgb(colors[2],(245,247,246))
    image=Image.new("RGB",(width,height),c3)
    px=image.load()
    for y in range(height):
        t=y/max(1,height-1)
        for x in range(width):
            s=x/max(1,width-1)
            blend=min(1.0,max(0.0,0.62*s+0.38*t))
            px[x,y]=tuple(round(c1[i]*(1-blend)+c3[i]*blend) for i in range(3))
    draw=ImageDraw.Draw(image,"RGBA")
    seed=int(hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],16)
    rng=random.Random(seed)
    for _ in range(7):
        radius=rng.randint(max(40,width//14),max(70,width//4))
        x=rng.randint(-radius,width+radius); y=rng.randint(-radius,height+radius)
        col=(*c2,rng.randint(18,55)) if rng.random()>.35 else (*c1,rng.randint(20,65))
        draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=col)
    image=image.filter(ImageFilter.GaussianBlur(radius=max(12,min(width,height)//55)))
    return image


async def _comfy_background(prompt: str, width: int, height: int) -> Image.Image:
    if not COMFYUI_BASE_URL or not COMFYUI_CHECKPOINT:
        raise RuntimeError("ComfyUI is not configured")
    seed=int.from_bytes(os.urandom(8),"big")%(2**63-1)
    workflow={
        "4":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":COMFYUI_CHECKPOINT}},
        "6":{"class_type":"CLIPTextEncode","inputs":{"text":prompt,"clip":["4",1]}},
        "7":{"class_type":"CLIPTextEncode","inputs":{"text":"text, watermark, logo, distorted, low quality","clip":["4",1]}},
        "5":{"class_type":"EmptyLatentImage","inputs":{"width":width,"height":height,"batch_size":1}},
        "3":{"class_type":"KSampler","inputs":{"seed":seed,"steps":24,"cfg":6.5,"sampler_name":"euler","scheduler":"normal","denoise":1,"model":["4",0],"positive":["6",0],"negative":["7",0],"latent_image":["5",0]}},
        "8":{"class_type":"VAEDecode","inputs":{"samples":["3",0],"vae":["4",2]}},
        "9":{"class_type":"SaveImage","inputs":{"filename_prefix":"project-visibility-bg","images":["8",0]}},
    }
    client_id=str(uuid.uuid4())
    async with httpx.AsyncClient(timeout=IMAGE_GEN_TIMEOUT) as client:
        queued=await client.post(f"{COMFYUI_BASE_URL}/prompt",json={"prompt":workflow,"client_id":client_id})
        queued.raise_for_status()
        prompt_id=str(queued.json().get("prompt_id") or "")
        if not prompt_id:
            raise RuntimeError("ComfyUI did not return prompt_id")
        for _ in range(120):
            await __import__("asyncio").sleep(2)
            history=await client.get(f"{COMFYUI_BASE_URL}/history/{prompt_id}")
            if history.status_code>=400:
                continue
            item=(history.json() or {}).get(prompt_id) or {}
            outputs=item.get("outputs") or {}
            images=((outputs.get("9") or {}).get("images") or [])
            if not images:
                continue
            meta=images[0]
            response=await client.get(
                f"{COMFYUI_BASE_URL}/view",
                params={"filename":meta.get("filename"),"subfolder":meta.get("subfolder",""),"type":meta.get("type","output")},
            )
            response.raise_for_status()
            image=Image.open(io.BytesIO(response.content)).convert("RGB")
            image.load()
            return image
    raise RuntimeError("ComfyUI generation timed out")


def _insert_generated(project_id: str, user_id: str, image: Image.Image, prompt: str, placement: str) -> dict[str,Any]:
    media.ensure_media_schema()
    with core.db() as con:
        count=int(con.execute("SELECT COUNT(*) AS n FROM project_images WHERE project_id=? AND user_id=?",(project_id,user_id)).fetchone()["n"])
    if count>=media.MAX_IMAGES_PER_PROJECT:
        raise HTTPException(409,f"A project can contain at most {media.MAX_IMAGES_PER_PROJECT} images")
    image_id=str(uuid.uuid4())
    base=f"{count+1:02d}-generated-background-{image_id[:8]}"
    project_dir=media.UPLOAD_ROOT/project_id
    variants=media._generate_variants(image,project_dir,base,logo=False,placement=placement,focal_x=50,focal_y=50)
    webps=[v for v in variants if v["format"]=="webp"]
    primary=max(webps or variants,key=lambda v:int(v["width"]))
    with core.db() as con:
        con.execute(
            """
            INSERT INTO project_images(
              id,project_id,user_id,original_name,stored_path,repo_path,mime_type,
              alt_text,placement,sort_order,created_at,variants_json,width,height,
              focal_x,focal_y,kind
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                image_id,project_id,user_id,"generated-background.webp",primary["stored_path"],
                primary["repo_path"],"image/webp",prompt[:180],media._safe_placement(placement),
                count,core.now_iso(),json.dumps(variants,ensure_ascii=False),image.width,image.height,
                50,50,"image",
            ),
        )
    return {"id":image_id,"repo_path":primary["repo_path"],"width":image.width,"height":image.height,"variants":[media._public_variant(v) for v in variants]}


@core.app.get("/projects/{project_id}/images/{image_id}/preview")
async def image_preview(project_id: str, image_id: str, user_id: str = Depends(core.current_user)):
    row=_image(project_id,image_id,user_id)
    path=Path(str(row["stored_path"]))
    if not path.is_file():
        raise HTTPException(404,"Image file is missing")
    return FileResponse(path,media_type="image/webp",filename=path.name)


@core.app.get("/projects/{project_id}/image-studio/history/{image_id}")
async def image_history(project_id: str,image_id: str,user_id: str=Depends(core.current_user)):
    _image(project_id,image_id,user_id)
    with core.db() as con:
        rows=con.execute(
            "SELECT id,created_at,width,height FROM project_image_history WHERE image_id=? AND project_id=? AND user_id=? ORDER BY created_at DESC LIMIT 20",
            (image_id,project_id,user_id),
        ).fetchall()
    return [dict(row) for row in rows]


@core.app.post("/projects/{project_id}/image-studio/edit")
async def edit_image(
    project_id: str,
    image_id: str = Form(...),
    rotate: int = Form(default=0),
    flip_horizontal: bool = Form(default=False),
    flip_vertical: bool = Form(default=False),
    brightness: float = Form(default=1.0),
    contrast: float = Form(default=1.0),
    saturation: float = Form(default=1.0),
    blur: float = Form(default=0.0),
    crop_x: float = Form(default=0),
    crop_y: float = Form(default=0),
    crop_w: float = Form(default=100),
    crop_h: float = Form(default=100),
    remove_background: bool = Form(default=False),
    background_mode: str = Form(default="preserve"),
    background_color: str = Form(default="#f5f7f6"),
    background_id: str = Form(default=""),
    shadow: bool = Form(default=True),
    background_file: UploadFile | None = File(default=None),
    user_id: str = Depends(core.current_user),
):
    _project(project_id,user_id)
    row=_image(project_id,image_id,user_id)
    snapshot_id=_snapshot(row)
    image=_open(str(row["stored_path"]))
    original_background: Image.Image | None=None
    try:
        image=_pct_crop(image,crop_x,crop_y,crop_w,crop_h)
        rotate=int(rotate)%360
        if rotate:
            image=image.rotate(-rotate,expand=True,resample=Image.Resampling.BICUBIC)
        if flip_horizontal:
            image=ImageOps.mirror(image)
        if flip_vertical:
            image=ImageOps.flip(image)
        image=ImageEnhance.Brightness(image).enhance(max(0.05,min(3.0,float(brightness))))
        image=ImageEnhance.Contrast(image).enhance(max(0.05,min(3.0,float(contrast))))
        image=ImageEnhance.Color(image).enhance(max(0.0,min(3.0,float(saturation))))
        if float(blur)>0:
            image=image.filter(ImageFilter.GaussianBlur(radius=min(30,float(blur))))

        bg_engine="none"
        if background_mode=="blur":
            original_background=image.copy()
        if remove_background or background_mode in {"transparent","color","blur","upload","image"}:
            image,bg_engine=_remove_background(image)

        bg: Image.Image | None=original_background
        if background_file and background_mode=="upload":
            raw=await background_file.read(MAX_BG_BYTES+1)
            if len(raw)>MAX_BG_BYTES:
                raise HTTPException(413,"Background image is too large")
            bg=media._prepare_source(raw)
        elif background_id and background_mode=="image":
            bgrow=_image(project_id,background_id,user_id)
            bg=_open(str(bgrow["stored_path"]))

        if background_mode!="preserve":
            image=_compose(image,mode=background_mode,color=background_color,background=bg,shadow=shadow)
        result=_save_result(row,image,"edit")
        result.update({"snapshot_id":snapshot_id,"background_engine":bg_engine})
        return result
    finally:
        try:image.close()
        except Exception:pass
        if 'bg' in locals() and bg is not None:
            try:bg.close()
            except Exception:pass
        if original_background is not None and original_background is not bg:
            try:original_background.close()
            except Exception:pass


@core.app.post("/projects/{project_id}/image-studio/generate-background")
async def generate_background(
    project_id: str,
    prompt: str = Form(...),
    width: int = Form(default=1536),
    height: int = Form(default=1024),
    placement: str = Form(default="gallery"),
    provider: str = Form(default="auto"),
    user_id: str = Depends(core.current_user),
):
    project=_project(project_id,user_id)
    prompt=" ".join(prompt.strip().split())
    if len(prompt)<3:
        raise HTTPException(422,"Background prompt is too short")
    width=max(512,min(2048,int(width)));height=max(512,min(2048,int(height)))
    width=round(width/64)*64;height=round(height/64)*64
    used="procedural"
    image: Image.Image | None=None
    if provider in {"auto","comfyui"} and COMFYUI_BASE_URL and COMFYUI_CHECKPOINT:
        try:
            image=await _comfy_background(prompt,width,height)
            used="comfyui"
        except Exception as exc:
            if provider=="comfyui":
                raise HTTPException(502,f"ComfyUI generation failed: {str(exc)[:300]}") from exc
    if image is None:
        image=_procedural_background(prompt,width,height,_project_brand(project))
    try:
        result=_insert_generated(project_id,user_id,image,prompt,placement)
        result["provider"]=used
        return result
    finally:
        image.close()


@core.app.post("/projects/{project_id}/image-studio/restore/{snapshot_id}")
async def restore_image(project_id: str,snapshot_id: str,user_id: str=Depends(core.current_user)):
    ensure_schema()
    with core.db() as con:
        snap=con.execute(
            "SELECT * FROM project_image_history WHERE id=? AND project_id=? AND user_id=?",
            (snapshot_id,project_id,user_id),
        ).fetchone()
    if not snap:
        raise HTTPException(404,"Image snapshot not found")
    row=_image(project_id,str(snap["image_id"]),user_id)
    _snapshot(row)
    image=_open(str(snap["stored_path"]))
    try:
        result=_save_result(row,image,"restore")
        result["restored_snapshot"]=snapshot_id
        return result
    finally:
        image.close()
