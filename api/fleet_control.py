"""Loopback-only fleet control adapter for Project Visibility.

The remote Agent Manager talks to this endpoint from the same Windows host.
It deliberately exposes a bounded operational command set instead of shell or
arbitrary Python execution.
"""

from __future__ import annotations

import hmac
import os
import re
from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

import api.main as core
import api.autonomous_supervisor as supervisor
import api.preflight as preflight
import api.capabilities as capabilities
import api.model_router as model_router
import api.production_queue as production_queue


class FleetCommand(BaseModel):
    command: str = Field(min_length=1, max_length=4000)


def _token() -> str:
    return os.getenv("PV_FLEET_TOKEN", "").strip()


def _fold(value: str) -> str:
    text = str(value or "").lower()
    text = text.translate(str.maketrans({"č": "c", "š": "s", "ž": "z", "ć": "c", "đ": "d"}))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _authorized(request: Request) -> bool:
    client = request.client.host if request.client else ""
    if client not in {"127.0.0.1", "::1", "localhost"}:
        return False
    expected = _token()
    supplied = request.headers.get("x-fleet-token", "").strip()
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def _help() -> dict[str, Any]:
    return {
        "commands": [
            "status",
            "preflight",
            "models",
            "capabilities",
            "queue",
            "run supervisor",
            "preglej in popravi",
        ],
        "note": "Only bounded operational actions are available; no arbitrary shell execution.",
    }


async def _status() -> dict[str, Any]:
    base = await core.health()
    queue = production_queue.queue_snapshot()
    return {
        "health": base,
        "supervisor": {
            "enabled": supervisor.SUPERVISOR_ENABLED,
            "active_recoveries": list(supervisor._active_recovery_tasks),
            "interval_seconds": supervisor.SUPERVISOR_INTERVAL_SECONDS,
        },
        "queue": queue,
        "routing": {
            "mode": model_router._routing_mode(),
            "fast_models": model_router._fast_models(),
            "expert_models": model_router._expert_models(),
        },
    }


@core.app.get("/internal/fleet/status")
async def fleet_status(request: Request):
    if not _authorized(request):
        raise HTTPException(401, "Fleet control authorization failed")
    return {"ok": True, "target": "project_visibility", "result": await _status()}


@core.app.post("/internal/fleet/command")
async def fleet_command(data: FleetCommand, request: Request):
    if not _authorized(request):
        raise HTTPException(401, "Fleet control authorization failed")

    command = data.command.strip()
    low = _fold(command)

    if low in {"help", "pomoc", "komande", "ukazi"} or "pokazi komande" in low:
        result = _help()
        action = "help"
    elif low in {"status", "health", "stanje"} or "preveri status" in low:
        result = await _status()
        action = "status"
    elif "preflight" in low or "production readiness" in low or "pripravljenost" in low:
        result = await preflight.production_preflight("fleet-control")
        action = "preflight"
    elif "model" in low:
        result = await model_router.model_summary("fleet-control")
        action = "models"
    elif "capabil" in low or "zmogljiv" in low or "funkcij" in low:
        result = await capabilities.agent_capabilities("fleet-control")
        action = "capabilities"
    elif "queue" in low or "vrst" in low:
        result = production_queue.queue_snapshot()
        action = "queue"
    elif (
        "supervisor" in low
        or "preglej in popravi" in low
        or "preveri in popravi" in low
        or "self heal" in low
        or "selfheal" in low
    ):
        result = await supervisor.supervisor_tick()
        action = "supervisor_run"
    else:
        raise HTTPException(
            422,
            {
                "error": "Unsupported Project Visibility fleet command",
                "help": _help(),
            },
        )

    return {
        "ok": True,
        "target": "project_visibility",
        "action": action,
        "command": command,
        "result": result,
    }
