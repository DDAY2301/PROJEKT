"""Runtime capability manifest for the local Project Visibility agent."""

from __future__ import annotations

import importlib.util
import os
import shutil
from typing import Any

from fastapi import Depends

import api.main as core
import api.model_router as model_router
import api.design_engine_v2 as design_engine_v2
import api.production_queue as production_queue
import api.visual_qa as visual_qa


def _binary(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    return {"available": bool(path), "path": path}


def _python_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


@core.app.get("/agent/capabilities")
async def agent_capabilities(user_id: str = Depends(core.current_user)):
    del user_id
    return {
        "agent": {
            "name": "Project Visibility Local Website Agent",
            "architecture": "planner -> design critic -> deterministic renderer -> bundle QA -> AI QA -> Chromium visual QA -> bounded repair -> Git delivery",
            "local_first": True,
            "primary_model": model_router._models()[0] if model_router._models() else core.OLLAMA_MODEL,
            "fallback_models": model_router._models()[1:],
            "model_mode": os.getenv("LOCAL_LLM_MODE", "auto"),
            "openai_compatible_local": bool(os.getenv("OPENAI_COMPAT_BASE_URL", "").strip()),
        },
        "features": {
            "persistent_quality_memory": True,
            "repo_map_context": True,
            "design_critic": os.getenv("DESIGN_CRITIC_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"},
            "safe_zip_import": True,
            "standalone_source_editor": True,
            "git_version_history": True,
            "one_click_rollback": True,
            "natural_language_revisions": True,
            "responsive_media": True,
            "focal_aware_hero_crop": True,
            "automatic_smart_focal": True,
            "image_studio": True,
            "non_destructive_image_history": True,
            "background_integration": True,
            "local_background_generation": True,
            "comfyui_background_generation": bool(os.getenv("COMFYUI_BASE_URL", "").strip() and os.getenv("COMFYUI_CHECKPOINT", "").strip()),
            "multi_backend_local_models": True,
            "webp": True,
            "avif": True,
            "private_preview": True,
            "chromium_visual_qa": True,
            "deterministic_bundle_qa": True,
            "self_fix": True,
            "autonomous_supervisor": True,
            "typed_decision_recovery": True,
            "bounded_retry_circuit_breaker": True,
            "restart_job_recovery": True,
            "github_delivery": True,
            "design_engine_v2": True,
            "quality_originality_gate_v2": True,
            "persistent_production_queue": True,
        },
        "runtime": {
            "git": _binary("git"),
            "node": _binary("node"),
            "ffmpeg": _binary("ffmpeg"),
            "libvips": _binary("vips"),
            "lighthouse": _binary("lighthouse"),
            "ollama": _binary("ollama"),
            "lmstudio_cli": _binary("lms"),
            "playwright_python": _python_module("playwright"),
            "pillow": _python_module("PIL"),
            "pyvips": _python_module("pyvips"),
            "rembg_python": _python_module("rembg"),
            "production_workers": production_queue.WORKER_COUNT,
            "model_concurrency": model_router.MODEL_CONCURRENCY,
            "design_motifs": len(design_engine_v2.MOTIFS),
            "visual_qa_concurrency": visual_qa.VISUAL_QA_CONCURRENCY,
        },
        "notes": {
            "libvips": "Optional. Current media engine uses Pillow LANCZOS/WebP/AVIF and focal-aware crops; libvips can become the hosted high-throughput backend.",
            "lighthouse": "Optional adapter. Core QA remains offline and does not depend on Lighthouse being installed.",
            "source_editor": "Core editor is offline-first and Git-backed. Monaco/CodeMirror/GrapesJS can be layered on top without changing the editor API.",
            "local_models": "Generation can route across Ollama plus an optional OpenAI-compatible local endpoint such as LM Studio, vLLM or SGLang.",
            "comfyui": "Optional. When COMFYUI_BASE_URL and COMFYUI_CHECKPOINT are set, Image Studio can generate AI backgrounds locally; otherwise brand-aware procedural generation remains available.",
            "rembg": "Optional. If installed, background removal uses rembg; otherwise a deterministic edge-colour fallback handles simple studio backgrounds.",
            "autonomous_supervisor": "Local typed-decision watchdog resumes interrupted work, separates build/publish recovery, applies backoff, and opens a circuit instead of retrying forever.",
        },
    }
