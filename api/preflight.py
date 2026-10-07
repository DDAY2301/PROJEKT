"""Production readiness preflight for the local website factory."""

from __future__ import annotations

import importlib.util
import os
import shutil
from typing import Any

import httpx
from fastapi import Depends

import api.main as core
import api.model_router as model_router
import api.production_queue as production_queue

MIN_DISK_BLOCK_GB = float(os.getenv("PREFLIGHT_MIN_DISK_BLOCK_GB", "2"))
MIN_DISK_WARN_GB = float(os.getenv("PREFLIGHT_MIN_DISK_WARN_GB", "10"))


async def _ollama_check() -> tuple[dict[str, Any], list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    info: dict[str, Any] = {"reachable": False, "primary_model": core.OLLAMA_MODEL, "models": []}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(f"{core.OLLAMA_BASE_URL}/api/tags")
        if response.status_code >= 400:
            blockers.append(f"Ollama returned HTTP {response.status_code}.")
            return info, blockers, warnings
        names = [str(item.get("name") or "") for item in (response.json().get("models") or [])]
        info.update({"reachable": True, "models": names})
        primary = model_router._fast_models()[0] if model_router._fast_models() else core.OLLAMA_MODEL
        info["primary_model"] = primary
        if primary not in names:
            blockers.append(f"Primary local model is not installed: {primary}")
        experts = model_router._expert_models()
        info["expert_models"] = experts
        if not experts:
            warnings.append("No expert KAT/Qwen3.6 model is installed; difficult repairs will fall back to the fast model.")
    except Exception as exc:
        blockers.append(f"Ollama is not reachable: {str(exc)[:180]}")
    return info, blockers, warnings


async def _github_check() -> tuple[dict[str, Any], list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    info: dict[str, Any] = {
        "configured": bool(core.GITHUB_TOKEN),
        "owner": core.GITHUB_OWNER,
        "authenticated_login": None,
    }
    if not core.GITHUB_TOKEN:
        blockers.append("GITHUB_TOKEN is not configured; customer delivery cannot complete.")
        return info, blockers, warnings
    try:
        async with httpx.AsyncClient(timeout=10, headers=core.github_headers()) as client:
            response = await client.get("https://api.github.com/user")
        if response.status_code >= 400:
            blockers.append(f"GitHub token validation failed with HTTP {response.status_code}.")
            return info, blockers, warnings
        login = str(response.json().get("login") or "")
        info["authenticated_login"] = login
        if login and login.lower() != str(core.GITHUB_OWNER).lower():
            blockers.append(
                f"GitHub token belongs to {login}, but GITHUB_OWNER is {core.GITHUB_OWNER}; repository delivery would target the wrong owner."
            )
    except Exception as exc:
        warnings.append(f"GitHub could not be validated right now: {str(exc)[:180]}")
    return info, blockers, warnings


@core.app.get("/agent/preflight")
async def production_preflight(user_id: str = Depends(core.current_user)):
    del user_id
    blockers: list[str] = []
    warnings: list[str] = []

    disk = shutil.disk_usage(core.DB_PATH.parent)
    free_gb = round(disk.free / (1024 ** 3), 2)
    if free_gb < MIN_DISK_BLOCK_GB:
        blockers.append(f"Free disk is critically low: {free_gb} GB.")
    elif free_gb < MIN_DISK_WARN_GB:
        warnings.append(f"Free disk is low for batch production: {free_gb} GB.")

    db_parent_writable = os.access(core.DB_PATH.parent, os.W_OK)
    if not db_parent_writable:
        blockers.append(f"Database directory is not writable: {core.DB_PATH.parent}")

    playwright_available = importlib.util.find_spec("playwright") is not None
    if not playwright_available:
        blockers.append("Playwright Python is not installed; Chromium Visual QA cannot run.")

    secret_strong = len(str(core.APP_SECRET)) >= 40 and str(core.APP_SECRET) != "dev-change-me"
    if not secret_strong:
        blockers.append("JWT signing secret is not production-safe.")

    ollama, ollama_blockers, ollama_warnings = await _ollama_check()
    github, github_blockers, github_warnings = await _github_check()
    blockers.extend(ollama_blockers)
    blockers.extend(github_blockers)
    warnings.extend(ollama_warnings)
    warnings.extend(github_warnings)

    queue = production_queue.queue_snapshot()
    queued = int((queue.get("states") or {}).get("queued", 0))
    running = int((queue.get("states") or {}).get("running", 0))
    workers_alive = int(queue.get("workers_alive") or 0)
    if workers_alive < production_queue.WORKER_COUNT:
        blockers.append(
            f"Production worker pool is unhealthy: {workers_alive}/{production_queue.WORKER_COUNT} workers alive."
        )
    if queued > 0 and workers_alive == 0:
        blockers.append("Production queue has waiting jobs but no live workers.")
    if queued > 50:
        warnings.append(f"Production queue is heavily loaded: {queued} queued jobs.")

    return {
        "ready": not blockers,
        "status": "READY" if not blockers else "BLOCKED",
        "blockers": blockers,
        "warnings": warnings,
        "checks": {
            "ollama": ollama,
            "github": github,
            "playwright": {"available": playwright_available},
            "database": {
                "path": str(core.DB_PATH),
                "directory_writable": db_parent_writable,
            },
            "disk": {"free_gb": free_gb, "warning_below_gb": MIN_DISK_WARN_GB},
            "security": {"strong_app_secret": secret_strong},
            "queue": {
                "workers": production_queue.WORKER_COUNT,
                "workers_alive": workers_alive,
                "worker_pool_healthy": bool(queue.get("worker_pool_healthy")),
                "queued": queued,
                "running": running,
            },
            "routing": {
                "mode": model_router._routing_mode(),
                "fast_models": model_router._fast_models(),
                "expert_models": model_router._expert_models(),
            },
        },
    }
