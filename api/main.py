import asyncio
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import bcrypt
import httpx
import jwt
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

APP_SECRET = os.getenv("APP_SECRET", "dev-change-me")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_OWNER = os.getenv("GITHUB_OWNER", "DDAY2301")
GITHUB_OUTPUT_PREFIX = os.getenv("GITHUB_OUTPUT_PREFIX", "generated-site-")
AUTO_FIX_INTERVAL_MINUTES = int(os.getenv("AUTO_FIX_INTERVAL_MINUTES", "60"))
MAX_AUTO_FIX_ATTEMPTS = int(os.getenv("MAX_AUTO_FIX_ATTEMPTS", "3"))
DB_PATH = Path(os.getenv("DB_PATH", "api/data/agent.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Project Visibility Autonomous Website Agent", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

scheduler = AsyncIOScheduler(timezone="UTC")


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash BLOB NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS projects (
              id TEXT PRIMARY KEY, user_id TEXT NOT NULL, package TEXT NOT NULL,
              status TEXT NOT NULL, name TEXT NOT NULL, repo_name TEXT,
              config_json TEXT NOT NULL, last_audit_json TEXT,
              auto_fix_attempts INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              FOREIGN KEY(user_id) REFERENCES users(id)
            );
            """
        )


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(RegisterIn):
    pass


class BrandConfig(BaseModel):
    primary_color: str = "#111827"
    secondary_color: str = "#84cc16"
    background_color: str = "#ffffff"
    text_color: str = "#111827"
    font_style: Literal["modern", "classic", "editorial", "tech", "minimal"] = "modern"
    mood: str = "clean, trustworthy, contemporary"


class PageConfig(BaseModel):
    slug: str
    title: str
    purpose: str = ""


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    package: Literal["Start", "Standard", "Premium"]
    organization: str
    programme: str = ""
    language: str = "sl"
    goal: str
    audience: str = ""
    tone: str = "professional and human"
    brand: BrandConfig = BrandConfig()
    pages: list[PageConfig] = []
    hero_title: str = ""
    hero_subtitle: str = ""
    cta_text: str = "Kontaktirajte nas"
    contact_email: EmailStr | None = None
    image_direction: str = "authentic, relevant, non-stock feeling"
    custom_requirements: str = ""


class ProjectPatch(BaseModel):
    config: dict


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def token_for(user_id: str):
    exp = datetime.now(timezone.utc) + timedelta(days=7)
    return jwt.encode({"sub": user_id, "exp": exp}, APP_SECRET, algorithm="HS256")


def current_user(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    try:
        payload = jwt.decode(authorization.split(" ", 1)[1], APP_SECRET, algorithms=["HS256"])
        return payload["sub"]
    except Exception:
        raise HTTPException(401, "Invalid or expired token")


async def ollama(prompt: str, system: str = "") -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    async with httpx.AsyncClient(timeout=240) as client:
        r = await client.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
        if r.status_code >= 400:
            raise HTTPException(503, f"Local model unavailable: {r.text[:300]}")
        return r.json().get("response", "")


def strip_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


async def design_site(config: dict) -> dict:
    page_budget = {"Start": 3, "Standard": 6, "Premium": 12}[config["package"]]
    system = "You are a senior product designer and web architect. Return JSON only."
    prompt = f"""
Create a complete information architecture and design specification for a production website.
Package allows at most {page_budget} pages.
Use this customer configuration:
{json.dumps(config, ensure_ascii=False)}
Return strict JSON with keys: site_name, seo_description, navigation, pages.
Each pages item must contain slug,title,meta_description,sections.
Each section: type,heading,body,cta(optional),image_prompt(optional).
No markdown. Do not invent legal claims or funding compliance claims.
"""
    raw = strip_fence(await ollama(prompt, system))
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(502, "Model did not return valid design JSON")


async def build_files(config: dict, spec: dict) -> dict[str, str]:
    system = "You are a senior frontend engineer. Return JSON only. Build accessible responsive static sites with no build step."
    prompt = f"""
Generate a complete website from the configuration and specification below.
CONFIG={json.dumps(config, ensure_ascii=False)}
SPEC={json.dumps(spec, ensure_ascii=False)}
Return strict JSON: {{"files": {{"index.html":"...","assets/site.css":"...","assets/site.js":"...", ...}}}}
Requirements:
- semantic HTML5, responsive CSS, keyboard accessibility, visible focus, sensible contrast
- no external frameworks, trackers, secrets, or inline third-party scripts
- navigation works on all generated pages
- all customer colors must be CSS variables
- image placeholders must use local paths under assets/images and descriptive alt text; do not fabricate photographs
- include title/meta description, OpenGraph basics, robots.txt and sitemap.xml
- no markdown fences
"""
    raw = strip_fence(await ollama(prompt, system))
    try:
        data = json.loads(raw)
        files = data["files"]
        if "index.html" not in files or "assets/site.css" not in files:
            raise ValueError("required files missing")
        return {str(k): str(v) for k, v in files.items()}
    except Exception:
        raise HTTPException(502, "Model did not return a valid website file bundle")


def static_audit(files: dict[str, str]) -> dict:
    issues = []
    html_files = {k: v for k, v in files.items() if k.endswith(".html")}
    if not html_files:
        issues.append({"severity": "critical", "code": "NO_HTML", "file": "", "message": "No HTML files generated"})
    for path, html in html_files.items():
        checks = [
            ("<title>", "MISSING_TITLE", "high"),
            ('name="description"', "MISSING_DESCRIPTION", "medium"),
            ("<main", "MISSING_MAIN", "medium"),
            ("lang=", "MISSING_LANG", "medium"),
        ]
        for needle, code, sev in checks:
            if needle.lower() not in html.lower():
                issues.append({"severity": sev, "code": code, "file": path, "message": f"{needle} missing"})
        if re.search(r'<img(?![^>]*\balt=)[^>]*>', html, re.I):
            issues.append({"severity": "medium", "code": "IMG_ALT", "file": path, "message": "Image without alt attribute"})
        if "javascript:" in html.lower():
            issues.append({"severity": "high", "code": "JS_URL", "file": path, "message": "javascript: URL found"})
    for path, content in files.items():
        if re.search(r'(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})', content):
            issues.append({"severity": "critical", "code": "SECRET", "file": path, "message": "Possible secret detected"})
    return {"passed": not any(i["severity"] in {"critical", "high"} for i in issues), "issues": issues}


async def ai_audit(files: dict[str, str], config: dict) -> dict:
    compact = {k: v[:14000] for k, v in files.items() if k.endswith((".html", ".css", ".js"))}
    system = "You are a strict website QA engineer. Return JSON only."
    prompt = f"""
Audit this static website bundle against user intent, broken navigation, UX, mobile-readiness, accessibility, SEO, obvious JavaScript errors and unsafe content.
CONFIG={json.dumps(config, ensure_ascii=False)}
FILES={json.dumps(compact, ensure_ascii=False)}
Return strict JSON: {{"passed":boolean,"issues":[{{"severity":"critical|high|medium|low","code":"...","file":"...","message":"..."}}]}}
Only report concrete issues.
"""
    try:
        return json.loads(strip_fence(await ollama(prompt, system)))
    except Exception:
        return {"passed": False, "issues": [{"severity": "high", "code": "AI_AUDIT_FAILED", "file": "", "message": "AI audit failed"}]}


async def fix_files(files: dict[str, str], issues: list[dict], config: dict) -> dict[str, str]:
    system = "You are a senior debugging engineer. Return JSON only. Make the smallest safe patch."
    prompt = f"""
Fix the concrete QA issues in this static website.
CONFIG={json.dumps(config, ensure_ascii=False)}
ISSUES={json.dumps(issues, ensure_ascii=False)}
FILES={json.dumps(files, ensure_ascii=False)}
Return strict JSON exactly as {{"files":{{...complete corrected files...}}}}.
Preserve customer design and content unless a reported issue requires change. Never insert credentials or remote execution code.
"""
    data = json.loads(strip_fence(await ollama(prompt, system)))
    return {str(k): str(v) for k, v in data["files"].items()}


def github_headers():
    if not GITHUB_TOKEN:
        raise HTTPException(503, "GITHUB_TOKEN is not configured")
    return {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


async def ensure_repo(repo_name: str):
    async with httpx.AsyncClient(timeout=60, headers=github_headers()) as client:
        r = await client.get(f"https://api.github.com/repos/{GITHUB_OWNER}/{repo_name}")
        if r.status_code == 404:
            r = await client.post("https://api.github.com/user/repos", json={"name": repo_name, "private": True, "auto_init": True})
        if r.status_code >= 400:
            raise HTTPException(502, f"GitHub repository error: {r.text[:300]}")


async def github_put_bundle(repo_name: str, files: dict[str, str], message: str):
    await ensure_repo(repo_name)
    async with httpx.AsyncClient(timeout=90, headers=github_headers()) as client:
        for path, content in files.items():
            url = f"https://api.github.com/repos/{GITHUB_OWNER}/{repo_name}/contents/{path}"
            existing = await client.get(url)
            payload = {"message": message, "content": __import__("base64").b64encode(content.encode()).decode()}
            if existing.status_code == 200:
                payload["sha"] = existing.json()["sha"]
            r = await client.put(url, json=payload)
            if r.status_code >= 400:
                raise HTTPException(502, f"GitHub write failed for {path}: {r.text[:300]}")


async def generate_project(project_id: str):
    with db() as con:
        row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            return
        config = json.loads(row["config_json"])
        con.execute("UPDATE projects SET status='designing',updated_at=? WHERE id=?", (now_iso(), project_id))
    spec = await design_site(config)
    files = await build_files(config, spec)
    audit1 = static_audit(files)
    audit2 = await ai_audit(files, config)
    issues = audit1["issues"] + audit2.get("issues", [])
    attempts = 0
    while any(i.get("severity") in {"critical", "high"} for i in issues) and attempts < MAX_AUTO_FIX_ATTEMPTS:
        attempts += 1
        files = await fix_files(files, issues, config)
        audit1 = static_audit(files)
        audit2 = await ai_audit(files, config)
        issues = audit1["issues"] + audit2.get("issues", [])
    repo_name = re.sub(r"[^a-z0-9-]+", "-", (GITHUB_OUTPUT_PREFIX + config["name"]).lower()).strip("-")[:90]
    await github_put_bundle(repo_name, files, f"Agent build for {config['name']}")
    status = "ready" if not any(i.get("severity") in {"critical", "high"} for i in issues) else "needs_review"
    with db() as con:
        con.execute(
            "UPDATE projects SET status=?,repo_name=?,last_audit_json=?,auto_fix_attempts=?,updated_at=? WHERE id=?",
            (status, repo_name, json.dumps({"issues": issues}, ensure_ascii=False), attempts, now_iso(), project_id),
        )


async def monitor_all_projects():
    with db() as con:
        rows = con.execute("SELECT id,status FROM projects WHERE status IN ('ready','needs_review')").fetchall()
    for row in rows:
        if row["status"] == "needs_review":
            try:
                await generate_project(row["id"])
            except Exception:
                pass


@app.on_event("startup")
async def startup():
    init_db()
    if not scheduler.running:
        scheduler.add_job(monitor_all_projects, "interval", minutes=AUTO_FIX_INTERVAL_MINUTES, id="self-heal", replace_existing=True)
        scheduler.start()


@app.get("/health")
async def health():
    return {"ok": True, "model": OLLAMA_MODEL, "github_configured": bool(GITHUB_TOKEN)}


@app.post("/auth/register")
async def register(data: RegisterIn):
    uid = str(uuid.uuid4())
    pw = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt())
    try:
        with db() as con:
            con.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(?,?,?,?)", (uid, data.email.lower(), pw, now_iso()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Email already registered")
    return {"token": token_for(uid)}


@app.post("/auth/login")
async def login(data: LoginIn):
    with db() as con:
        row = con.execute("SELECT * FROM users WHERE email=?", (data.email.lower(),)).fetchone()
    if not row or not bcrypt.checkpw(data.password.encode(), row["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    return {"token": token_for(row["id"])}


@app.post("/projects")
async def create_project(data: ProjectCreate, user_id: str = Depends(current_user)):
    pid = str(uuid.uuid4())
    cfg = data.model_dump(mode="json")
    with db() as con:
        con.execute(
            "INSERT INTO projects(id,user_id,package,status,name,config_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (pid, user_id, data.package, "queued", data.name, json.dumps(cfg, ensure_ascii=False), now_iso(), now_iso()),
        )
    asyncio.create_task(generate_project(pid))
    return {"id": pid, "status": "queued"}


@app.get("/projects")
async def list_projects(user_id: str = Depends(current_user)):
    with db() as con:
        rows = con.execute("SELECT id,name,package,status,repo_name,last_audit_json,created_at,updated_at FROM projects WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/projects/{project_id}")
async def get_project(project_id: str, user_id: str = Depends(current_user)):
    with db() as con:
        row = con.execute("SELECT * FROM projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    out = dict(row)
    out["config"] = json.loads(out.pop("config_json"))
    out["last_audit"] = json.loads(out.pop("last_audit_json")) if out.get("last_audit_json") else None
    return out


@app.patch("/projects/{project_id}")
async def patch_project(project_id: str, data: ProjectPatch, user_id: str = Depends(current_user)):
    with db() as con:
        row = con.execute("SELECT * FROM projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")
        current = json.loads(row["config_json"])
        current.update(data.config)
        con.execute("UPDATE projects SET config_json=?,status='queued',auto_fix_attempts=0,updated_at=? WHERE id=?", (json.dumps(current, ensure_ascii=False), now_iso(), project_id))
    asyncio.create_task(generate_project(project_id))
    return {"id": project_id, "status": "queued"}


@app.post("/projects/{project_id}/audit")
async def trigger_audit(project_id: str, user_id: str = Depends(current_user)):
    with db() as con:
        row = con.execute("SELECT id FROM projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    asyncio.create_task(generate_project(project_id))
    return {"id": project_id, "status": "audit_queued"}
