"""Local-first multi-backend model router with fallback and telemetry.

Project Visibility keeps the existing Ollama interface for the rest of the code,
but the router can now use either Ollama or any local OpenAI-compatible server
(LM Studio, vLLM, SGLang, llama.cpp-compatible gateways, etc.).

Configuration:
- LOCAL_LLM_MODE=auto|ollama|openai
- OLLAMA_FALLBACK_MODELS=model-a,model-b
- OPENAI_COMPAT_BASE_URL=http://127.0.0.1:1234/v1
- OPENAI_COMPAT_API_KEY=optional-local-token
- OPENAI_COMPAT_MODELS=model-a,model-b

In auto mode Ollama remains the first backend for backwards compatibility and
the OpenAI-compatible backend is used as a fallback when configured.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Depends

import api.main as core

MODEL_CONCURRENCY = max(1, min(8, int(os.getenv("MODEL_CONCURRENCY", "1"))))
_MODEL_SEMAPHORE = asyncio.Semaphore(MODEL_CONCURRENCY)


@dataclass(frozen=True)
class Candidate:
    provider: str
    model: str
    base_url: str


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        value = (value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _ollama_models() -> list[str]:
    return _dedupe(
        [core.OLLAMA_MODEL]
        + [x.strip() for x in os.getenv("OLLAMA_FALLBACK_MODELS", "").split(",")]
    )


def _openai_models() -> list[str]:
    return _dedupe([x.strip() for x in os.getenv("OPENAI_COMPAT_MODELS", "").split(",")])


def _mode() -> str:
    mode = os.getenv("LOCAL_LLM_MODE", "auto").strip().lower()
    return mode if mode in {"auto", "ollama", "openai"} else "auto"


def _openai_base() -> str:
    return os.getenv("OPENAI_COMPAT_BASE_URL", "").strip().rstrip("/")


def _candidates() -> list[Candidate]:
    mode = _mode()
    out: list[Candidate] = []
    if mode in {"auto", "ollama"}:
        out.extend(Candidate("ollama", model, core.OLLAMA_BASE_URL.rstrip("/")) for model in _ollama_models())
    if mode in {"auto", "openai"} and _openai_base():
        out.extend(Candidate("openai", model, _openai_base()) for model in _openai_models())
    return out


# Backwards-compatible helper used by capability reporting.
def _models() -> list[str]:
    return _dedupe([candidate.model for candidate in _candidates()])


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
        columns = {row["name"] for row in con.execute("PRAGMA table_info(agent_model_runs)").fetchall()}
        if "provider" not in columns:
            con.execute("ALTER TABLE agent_model_runs ADD COLUMN provider TEXT NOT NULL DEFAULT 'ollama'")


def _record(
    provider: str,
    model: str,
    status: str,
    prompt: str,
    response: str,
    latency_ms: int,
    error: str = "",
) -> None:
    ensure_schema()
    with core.db() as con:
        con.execute(
            "INSERT INTO agent_model_runs(id,provider,model,status,prompt_chars,response_chars,latency_ms,error,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                provider,
                model,
                status,
                len(prompt),
                len(response or ""),
                int(latency_ms),
                (error or "")[:600],
                core.now_iso(),
            ),
        )


async def _ollama_generate(
    client: httpx.AsyncClient,
    candidate: Candidate,
    prompt: str,
    system: str,
    *,
    json_mode: bool,
    num_predict: int,
    temperature: float,
    num_ctx: int,
) -> str:
    payload: dict[str, Any] = {
        "model": candidate.model,
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
    response = await client.post(f"{candidate.base_url}/api/generate", json=payload)
    response.raise_for_status()
    return str(response.json().get("response") or "").strip()


async def _openai_generate(
    client: httpx.AsyncClient,
    candidate: Candidate,
    prompt: str,
    system: str,
    *,
    json_mode: bool,
    num_predict: int,
    temperature: float,
) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload: dict[str, Any] = {
        "model": candidate.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": num_predict,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("OPENAI_COMPAT_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    response = await client.post(
        f"{candidate.base_url}/chat/completions",
        json=payload,
        headers=headers,
    )
    # Some compatible servers do not implement response_format. Retry once
    # without it rather than discarding an otherwise capable local model.
    if response.status_code >= 400 and json_mode:
        payload.pop("response_format", None)
        response = await client.post(
            f"{candidate.base_url}/chat/completions",
            json=payload,
            headers=headers,
        )
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        return "".join(str(item.get("text") or "") for item in content if isinstance(item, dict)).strip()
    return str(content or "").strip()


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
    candidates = _candidates()
    if not candidates:
        raise RuntimeError("No local LLM backend is configured")

    async with _MODEL_SEMAPHORE:
        last_error: Exception | None = None
        for candidate in candidates:
            started = time.perf_counter()
            response_text = ""
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    if candidate.provider == "openai":
                        response_text = await _openai_generate(
                            client,
                            candidate,
                            prompt,
                            system,
                            json_mode=json_mode,
                            num_predict=num_predict,
                            temperature=temperature,
                        )
                    else:
                        response_text = await _ollama_generate(
                            client,
                            candidate,
                            prompt,
                            system,
                            json_mode=json_mode,
                            num_predict=num_predict,
                            temperature=temperature,
                            num_ctx=num_ctx,
                        )
                latency = round((time.perf_counter() - started) * 1000)
                if not response_text:
                    raise RuntimeError("model returned an empty response")
                _record(candidate.provider, candidate.model, "ok", prompt, response_text, latency)
                return response_text
            except Exception as exc:
                latency = round((time.perf_counter() - started) * 1000)
                _record(candidate.provider, candidate.model, "failed", prompt, response_text, latency, str(exc))
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
            SELECT provider,model,
                   COUNT(*) AS calls,
                   SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS successes,
                   ROUND(AVG(latency_ms)) AS avg_latency_ms,
                   SUM(prompt_chars) AS prompt_chars,
                   SUM(response_chars) AS response_chars
            FROM agent_model_runs
            GROUP BY provider,model
            ORDER BY calls DESC
            """
        ).fetchall()
        recent = con.execute(
            "SELECT provider,model,status,latency_ms,error,created_at FROM agent_model_runs ORDER BY created_at DESC LIMIT 20"
        ).fetchall()

    candidates = _candidates()
    return {
        "mode": _mode(),
        "configured_models": [c.model for c in candidates],
        "primary": candidates[0].model if candidates else None,
        "backends": [
            {
                "provider": c.provider,
                "model": c.model,
                "base_url": c.base_url,
            }
            for c in candidates
        ],
        "stats": [dict(row) for row in totals],
        "recent": [dict(row) for row in recent],
    }


core.ollama = routed_ollama
