"""Provider-light local model router with fallback and telemetry.

The product remains Ollama-first and fully local. A comma-separated
OLLAMA_FALLBACK_MODELS value can add stronger or cheaper local models without
changing generation code. Every call is measured in SQLite so model quality,
latency and fallback frequency can be benchmarked instead of guessed.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import httpx
from fastapi import Depends

import api.main as core


def _models() -> list[str]:
    raw = [core.OLLAMA_MODEL]
    raw.extend(x.strip() for x in os.getenv("OLLAMA_FALLBACK_MODELS", "").split(",") if x.strip())
    out: list[str] = []
    for model in raw:
        if model and model not in out:
            out.append(model)
    return out


def ensure_schema() -> None:
    with core.db() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_model_runs (
              id TEXT PRIMARY KEY,
              model TEXT NOT NULL,
              status TEXT NOT NULL,
              prompt_chars INTEGER NOT NULL,
              response_chars INTEGER NOT NULL DEFAULT 0,
              latency_ms INTEGER NOT NULL DEFAULT 0,
              error TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL
            )
            """
        )


def _record(model: str, status: str, prompt: str, response: str, latency_ms: int, error: str = "") -> None:
    ensure_schema()
    with core.db() as con:
        con.execute(
            "INSERT INTO agent_model_runs(id,model,status,prompt_chars,response_chars,latency_ms,error,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                model,
                status,
                len(prompt),
                len(response or ""),
                int(latency_ms),
                (error or "")[:600],
                core.now_iso(),
            ),
        )


async def generate(
    prompt: str,
    system: str = "",
    *,
    json_mode: bool = False,
    timeout: int = 360,
    num_predict: int = 4096,
    temperature: float = 0.15,
    num_ctx: int = 8192,
) -> str:
    last_error: Exception | None = None
    for model in _models():
        started = time.perf_counter()
        response_text = ""
        try:
            payload: dict[str, Any] = {
                "model": model,
                "prompt": prompt,
                "system": system,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_ctx": num_ctx,
                    "num_predict": num_predict,
                },
            }
            if json_mode:
                payload["format"] = "json"
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{core.OLLAMA_BASE_URL}/api/generate", json=payload)
                response.raise_for_status()
                response_text = str(response.json().get("response") or "").strip()
            latency = round((time.perf_counter() - started) * 1000)
            if not response_text:
                raise RuntimeError("model returned an empty response")
            _record(model, "ok", prompt, response_text, latency)
            return response_text
        except Exception as exc:
            latency = round((time.perf_counter() - started) * 1000)
            _record(model, "failed", prompt, response_text, latency, str(exc))
            last_error = exc
            continue
    raise RuntimeError(f"All configured local models failed: {last_error or 'unknown error'}")


async def routed_ollama(prompt: str, system: str = "") -> str:
    return await generate(
        prompt,
        system,
        json_mode=False,
        timeout=240,
        num_predict=4096,
        temperature=0.2,
        num_ctx=8192,
    )


@core.app.get("/agent/models")
async def model_summary(user_id: str = Depends(core.current_user)):
    del user_id
    ensure_schema()
    with core.db() as con:
        totals = con.execute(
            """
            SELECT model,
                   COUNT(*) AS calls,
                   SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS successes,
                   ROUND(AVG(latency_ms)) AS avg_latency_ms,
                   SUM(prompt_chars) AS prompt_chars,
                   SUM(response_chars) AS response_chars
            FROM agent_model_runs
            GROUP BY model
            ORDER BY calls DESC
            """
        ).fetchall()
        recent = con.execute(
            "SELECT model,status,latency_ms,error,created_at FROM agent_model_runs ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    return {
        "configured_models": _models(),
        "primary": core.OLLAMA_MODEL,
        "stats": [dict(row) for row in totals],
        "recent": [dict(row) for row in recent],
    }


core.ollama = routed_ollama
