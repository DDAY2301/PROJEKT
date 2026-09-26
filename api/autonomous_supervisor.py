"""Autonomous typed-decision supervisor for long-running Project Visibility jobs.

Inspired by the public TypeSafe/Jev pattern: turn application state into a
small, typed decision that normal code can safely branch on. This module does
not depend on Jev or any hosted decision API; it keeps recovery local-first and
deterministic.

The supervisor replaces the legacy blind self-heal loop with bounded,
observable recovery:
- resume queued work after process restarts;
- detect stale build / QA / revision / publishing states;
- retry build and publishing separately;
- apply exponential cooldown and a recovery circuit breaker;
- never auto-advance payment states;
- require human review when permissions or repeated failures cannot be solved
  safely by another retry.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, HTTPException

import api.main as core
import api.retry_routes as retry_routes

logger = logging.getLogger("project_visibility.supervisor")

SUPERVISOR_ENABLED = os.getenv("SUPERVISOR_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
SUPERVISOR_INTERVAL_SECONDS = max(30, int(os.getenv("SUPERVISOR_INTERVAL_SECONDS", "120")))
SUPERVISOR_STALE_SECONDS = max(90, int(os.getenv("SUPERVISOR_STALE_SECONDS", "900")))
SUPERVISOR_QUEUE_STALE_SECONDS = max(20, int(os.getenv("SUPERVISOR_QUEUE_STALE_SECONDS", "90")))
SUPERVISOR_MAX_RECOVERIES = max(1, int(os.getenv("SUPERVISOR_MAX_RECOVERIES", "3")))
SUPERVISOR_COOLDOWN_SECONDS = max(30, int(os.getenv("SUPERVISOR_COOLDOWN_SECONDS", "180")))
SUPERVISOR_MIN_DISK_GB = max(0.25, float(os.getenv("SUPERVISOR_MIN_DISK_GB", "1.0")))

ACTIVE_BUILD_STATES = {
    "designing",
    "building",
    "auditing",
    "visual_qa",
    "fixing",
    "revising",
    "repository_ready",
}
PAYMENT_HOLD_STATES = {"ready_for_payment", "payment_pending"}

CHOICES = (
    "wait",
    "retry_build",
    "retry_publish",
    "hold_payment",
    "complete",
    "human_review",
)

PROCESS_INSTANCE_ID = uuid.uuid4().hex
PROCESS_STARTED_AT = datetime.now(timezone.utc)
_active_recovery_tasks: dict[str, asyncio.Task] = {}
_tick_lock = asyncio.Lock()


@dataclass(frozen=True)
class TypedDecision:
    choice: str
    confidence: float
    risk_score: int
    autonomous: bool
    reason_code: str
    next_check_seconds: int

    def payload(self) -> dict[str, Any]:
        confidence = max(0.0, min(1.0, float(self.confidence)))
        probabilities = {name: 0.0 for name in CHOICES}
        if self.choice in probabilities:
            probabilities[self.choice] = round(confidence, 4)
            remainder = round(max(0.0, 1.0 - confidence), 4)
            fallback = "human_review" if self.choice != "human_review" else "wait"
            probabilities[fallback] = remainder
        return {
            "type": "choice",
            "choice": self.choice,
            "confidence": round(confidence, 4),
            "probabilities": probabilities,
            "risk_score": int(max(0, min(10, self.risk_score))),
            "autonomous": bool(self.autonomous),
            "reason_code": self.reason_code,
            "next_check_seconds": int(max(30, self.next_check_seconds)),
        }


def ensure_supervisor_schema() -> None:
    with core.db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS agent_supervisor_state (
              project_id TEXT PRIMARY KEY,
              recovery_count INTEGER NOT NULL DEFAULT 0,
              last_choice TEXT NOT NULL DEFAULT '',
              last_reason_code TEXT NOT NULL DEFAULT '',
              last_decision_json TEXT NOT NULL DEFAULT '{}',
              last_action_at TEXT,
              last_seen_status TEXT NOT NULL DEFAULT '',
              last_seen_project_updated_at TEXT NOT NULL DEFAULT '',
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_supervisor_events (
              id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              choice TEXT NOT NULL,
              confidence REAL NOT NULL,
              risk_score INTEGER NOT NULL,
              autonomous INTEGER NOT NULL,
              reason_code TEXT NOT NULL,
              state_json TEXT NOT NULL,
              decision_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_supervisor_events_project_created
              ON agent_supervisor_events(project_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS agent_supervisor_lease (
              name TEXT PRIMARY KEY,
              owner_id TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _acquire_supervisor_lease() -> bool:
    """Acquire a short DB lease so only one process performs recovery actions."""
    ensure_supervisor_schema()
    now = _now()
    ttl = max(120, SUPERVISOR_INTERVAL_SECONDS * 3)
    expires = datetime.fromtimestamp(now.timestamp() + ttl, tz=timezone.utc).isoformat()
    try:
        with core.db() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT owner_id,expires_at FROM agent_supervisor_lease WHERE name='global'"
            ).fetchone()
            if row:
                expiry = _parse_time(row["expires_at"])
                if row["owner_id"] != PROCESS_INSTANCE_ID and expiry and expiry > now:
                    return False
            con.execute(
                """
                INSERT INTO agent_supervisor_lease(name,owner_id,expires_at,updated_at)
                VALUES('global',?,?,?)
                ON CONFLICT(name) DO UPDATE SET
                  owner_id=excluded.owner_id,
                  expires_at=excluded.expires_at,
                  updated_at=excluded.updated_at
                """,
                (PROCESS_INSTANCE_ID, expires, core.now_iso()),
            )
        return True
    except Exception:
        logger.exception("Could not acquire supervisor lease")
        return False


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _age_seconds(value: str | None) -> float:
    parsed = _parse_time(value)
    if not parsed:
        return 10**9
    return max(0.0, (_now() - parsed).total_seconds())


def _read_json(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _supervisor_row(project_id: str) -> dict[str, Any]:
    ensure_supervisor_schema()
    with core.db() as con:
        row = con.execute(
            "SELECT * FROM agent_supervisor_state WHERE project_id=?",
            (project_id,),
        ).fetchone()
    if row:
        return dict(row)
    return {
        "project_id": project_id,
        "recovery_count": 0,
        "last_choice": "",
        "last_reason_code": "",
        "last_decision_json": "{}",
        "last_action_at": None,
        "last_seen_status": "",
        "last_seen_project_updated_at": "",
        "updated_at": core.now_iso(),
    }


def _issue_summary(audit: dict[str, Any]) -> dict[str, Any]:
    issues = [item for item in (audit.get("issues") or []) if isinstance(item, dict)]
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    codes: list[str] = []
    messages: list[str] = []
    for issue in issues:
        severity = str(issue.get("severity") or "").lower()
        if severity in counts:
            counts[severity] += 1
        code = str(issue.get("code") or "").strip()
        if code and code not in codes:
            codes.append(code)
        message = str(issue.get("message") or "").strip()
        if message:
            messages.append(message[:240])
    return {
        "counts": counts,
        "codes": codes[:24],
        "messages": messages[:12],
        "severe": counts["critical"] + counts["high"],
        "total": len(issues),
    }


def _state_from_project(row: dict[str, Any], supervisor: dict[str, Any]) -> dict[str, Any]:
    audit = _read_json(row.get("last_audit_json"))
    try:
        config = json.loads(row.get("config_json") or "{}")
    except Exception:
        config = {}
    issues = _issue_summary(audit)
    visual = audit.get("visual_qa") if isinstance(audit.get("visual_qa"), dict) else {}
    return {
        "project_id": row["id"],
        "status": str(row.get("status") or ""),
        "imported_site": bool(config.get("_imported_site")),
        "status_age_seconds": round(_age_seconds(row.get("updated_at")), 1),
        "updated_at": row.get("updated_at"),
        "predates_process": bool(
            (_parse_time(row.get("updated_at")) or _now()) < PROCESS_STARTED_AT
        ),
        "repo_name": row.get("repo_name") or "",
        "repository_ready": bool(audit.get("repository_ready") or row.get("repo_name")),
        "public_live": bool(audit.get("public_live")),
        "quality_gate_passed": bool(audit.get("quality_gate_passed")),
        "payment_blocked": bool(audit.get("payment_blocked")),
        "payment_stage": audit.get("payment_stage"),
        "publish_action_required": audit.get("publish_action_required"),
        "failure_stage": audit.get("failure_stage"),
        "error_type": audit.get("error_type"),
        "visual_score": visual.get("score"),
        "visual_available": bool(visual.get("available")),
        "issues": issues,
        "auto_fix_attempts": int(row.get("auto_fix_attempts") or 0),
        "recovery_count": int(supervisor.get("recovery_count") or 0),
        "seconds_since_recovery": round(_age_seconds(supervisor.get("last_action_at")), 1)
        if supervisor.get("last_action_at")
        else None,
    }


def _cooldown_seconds(recovery_count: int) -> int:
    exponent = max(0, min(4, recovery_count - 1))
    return SUPERVISOR_COOLDOWN_SECONDS * (2**exponent)


def decide(state: dict[str, Any], runtime: dict[str, Any] | None = None) -> TypedDecision:
    """Return a small typed decision from current application state."""
    runtime = runtime or {}
    status = state["status"]
    recovery_count = int(state.get("recovery_count") or 0)
    age = float(state.get("status_age_seconds") or 0)
    severe = int((state.get("issues") or {}).get("severe") or 0)
    codes = set((state.get("issues") or {}).get("codes") or [])
    messages = " ".join((state.get("issues") or {}).get("messages") or []).lower()

    if runtime and float(runtime.get("disk_free_gb") or 9999) < SUPERVISOR_MIN_DISK_GB:
        return TypedDecision("human_review", 0.99, 10, False, "runtime_disk_low", 600)

    if status == "ready":
        return TypedDecision("complete", 1.0, 0, False, "project_ready", 3600)

    if status in PAYMENT_HOLD_STATES:
        return TypedDecision("hold_payment", 1.0, 1, False, "payment_boundary", 1800)

    if state.get("imported_site") and status in {"importing", "repository_ready", "auditing"}:
        if age < SUPERVISOR_STALE_SECONDS * 2:
            return TypedDecision("wait", 1.0, 2, False, "zip_import_owned_by_import_worker", 90)
        return TypedDecision("human_review", 0.99, 7, False, "zip_import_stalled", 1800)

    if state.get("imported_site") and status == "failed":
        return TypedDecision("human_review", 0.99, 8, False, "zip_import_failed", 1800)

    if state.get("imported_site") and status == "needs_review":
        return TypedDecision("wait", 1.0, 3, False, "imported_site_preserve_source", 1800)

    if state.get("publish_action_required") == "github_pages_permission":
        return TypedDecision("human_review", 1.0, 8, False, "github_pages_permission", 1800)

    permission_failure = (
        "permission" in messages
        or "forbidden" in messages
        or "authentication" in messages
        or "token" in messages
        or "GITHUB_PAGES_PERMISSION" in codes
    )
    if permission_failure:
        return TypedDecision("human_review", 0.99, 9, False, "external_permission_required", 1800)

    last_action_age = state.get("seconds_since_recovery")
    if last_action_age is not None:
        cooldown = _cooldown_seconds(recovery_count)
        if float(last_action_age) < cooldown:
            return TypedDecision("wait", 1.0, 2, False, "recovery_backoff", max(30, cooldown - int(last_action_age)))

    if status == "publishing":
        if state.get("predates_process") and recovery_count < SUPERVISOR_MAX_RECOVERIES:
            return TypedDecision("retry_publish", 0.99, 4, True, "orphaned_publish_after_restart", 60)
        if age < SUPERVISOR_STALE_SECONDS:
            return TypedDecision("wait", 1.0, 2, False, "publish_in_progress", 60)
        if recovery_count >= SUPERVISOR_MAX_RECOVERIES:
            return TypedDecision("human_review", 0.99, 8, False, "publish_circuit_open", 1800)
        return TypedDecision("retry_publish", 0.99, 4, True, "stale_publish_resume", 60)

    if status == "queued":
        if state.get("predates_process") and recovery_count < SUPERVISOR_MAX_RECOVERIES:
            if runtime and not runtime.get("model_online", True):
                return TypedDecision("wait", 0.99, 5, False, "model_backend_offline", 120)
            return TypedDecision("retry_build", 0.99, 3, True, "orphaned_queue_after_restart", 60)
        if age < SUPERVISOR_QUEUE_STALE_SECONDS:
            return TypedDecision("wait", 1.0, 1, False, "queue_grace_period", 30)
        if recovery_count >= SUPERVISOR_MAX_RECOVERIES:
            return TypedDecision("human_review", 0.99, 7, False, "build_circuit_open", 1800)
        if runtime and not runtime.get("model_online", True):
            return TypedDecision("wait", 0.99, 5, False, "model_backend_offline", 120)
        return TypedDecision("retry_build", 0.99, 3, True, "queued_after_restart", 60)

    if status in ACTIVE_BUILD_STATES:
        if state.get("predates_process") and recovery_count < SUPERVISOR_MAX_RECOVERIES:
            if runtime and not runtime.get("model_online", True):
                return TypedDecision("wait", 0.99, 5, False, "model_backend_offline", 120)
            return TypedDecision("retry_build", 0.99, 5, True, "orphaned_build_after_restart", 60)
        if age < SUPERVISOR_STALE_SECONDS:
            return TypedDecision("wait", 1.0, 2, False, "work_in_progress", 60)
        if recovery_count >= SUPERVISOR_MAX_RECOVERIES:
            return TypedDecision("human_review", 0.99, 8, False, "stale_build_circuit_open", 1800)
        if runtime and not runtime.get("model_online", True):
            return TypedDecision("wait", 0.99, 5, False, "model_backend_offline", 120)
        return TypedDecision("retry_build", 0.98, 5, True, "stale_build_recovery", 60)

    if status == "failed":
        if recovery_count >= SUPERVISOR_MAX_RECOVERIES:
            return TypedDecision("human_review", 0.99, 9, False, "failure_circuit_open", 1800)
        if runtime and not runtime.get("model_online", True):
            return TypedDecision("wait", 0.99, 6, False, "model_backend_offline", 120)
        failure_stage = str(state.get("failure_stage") or "").lower()
        publish_failure = (
            state.get("repository_ready")
            and (
                "publish" in failure_stage
                or "publication" in failure_stage
                or "PUBLISH_RETRY_FAILED" in codes
            )
        )
        if publish_failure:
            return TypedDecision("retry_publish", 0.98, 5, True, "failed_publish_recovery", 60)
        return TypedDecision("retry_build", 0.96, 6, True, "failed_build_recovery", 60)

    if status == "needs_review":
        if recovery_count >= SUPERVISOR_MAX_RECOVERIES:
            return TypedDecision("human_review", 0.99, 8, False, "quality_circuit_open", 1800)
        if runtime and not runtime.get("model_online", True):
            return TypedDecision("wait", 0.99, 5, False, "model_backend_offline", 120)
        if state.get("repository_ready") and not state.get("public_live") and severe == 0 and not state.get("payment_blocked"):
            return TypedDecision("retry_publish", 0.93, 4, True, "repository_ready_not_live", 90)
        return TypedDecision("retry_build", 0.92, 5 if severe else 4, True, "quality_retry", 120)

    return TypedDecision("human_review", 0.9, 6, False, "unknown_project_state", 1800)


async def runtime_health() -> dict[str, Any]:
    data_root = Path(core.DB_PATH).resolve().parent
    try:
        disk = shutil.disk_usage(data_root)
        disk_free_gb = round(disk.free / (1024**3), 2)
    except Exception:
        disk_free_gb = 9999.0

    mode = os.getenv("LOCAL_LLM_MODE", "auto").strip().lower()
    model_online = False
    model_endpoint_kind = "none"
    openai_base = os.getenv("OPENAI_COMPAT_BASE_URL", "").strip().rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            if mode in {"auto", "ollama"}:
                try:
                    response = await client.get(f"{core.OLLAMA_BASE_URL}/api/tags")
                    if response.status_code == 200:
                        model_online = True
                        model_endpoint_kind = "ollama"
                except Exception:
                    pass

            if not model_online and mode in {"auto", "openai"} and openai_base:
                headers = {}
                key = os.getenv("OPENAI_COMPAT_API_KEY", "").strip()
                if key:
                    headers["Authorization"] = f"Bearer {key}"
                try:
                    response = await client.get(f"{openai_base}/models", headers=headers)
                    if 200 <= response.status_code < 400:
                        model_online = True
                        model_endpoint_kind = "openai-compatible"
                except Exception:
                    pass
    except Exception:
        model_online = False

    return {
        "model_online": model_online,
        "model_mode": mode,
        "model_endpoint_kind": model_endpoint_kind,
        "github_configured": bool(core.GITHUB_TOKEN),
        "disk_free_gb": disk_free_gb,
        "disk_guard_gb": SUPERVISOR_MIN_DISK_GB,
    }


def _save_decision(
    project_state: dict[str, Any],
    supervisor: dict[str, Any],
    decision: TypedDecision,
    *,
    action_taken: bool,
) -> None:
    ensure_supervisor_schema()
    now = core.now_iso()
    payload = decision.payload()
    decision_changed = (
        supervisor.get("last_choice") != decision.choice
        or supervisor.get("last_reason_code") != decision.reason_code
        or supervisor.get("last_seen_project_updated_at") != str(project_state.get("updated_at") or "")
    )

    recovery_count = int(supervisor.get("recovery_count") or 0)
    if action_taken and decision.choice in {"retry_build", "retry_publish"}:
        recovery_count += 1
    elif decision.choice in {"complete", "hold_payment"}:
        recovery_count = 0

    with core.db() as con:
        con.execute(
            """
            INSERT INTO agent_supervisor_state(
              project_id,recovery_count,last_choice,last_reason_code,last_decision_json,
              last_action_at,last_seen_status,last_seen_project_updated_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(project_id) DO UPDATE SET
              recovery_count=excluded.recovery_count,
              last_choice=excluded.last_choice,
              last_reason_code=excluded.last_reason_code,
              last_decision_json=excluded.last_decision_json,
              last_action_at=CASE
                WHEN excluded.last_action_at IS NOT NULL THEN excluded.last_action_at
                ELSE agent_supervisor_state.last_action_at
              END,
              last_seen_status=excluded.last_seen_status,
              last_seen_project_updated_at=excluded.last_seen_project_updated_at,
              updated_at=excluded.updated_at
            """,
            (
                project_state["project_id"],
                recovery_count,
                decision.choice,
                decision.reason_code,
                json.dumps(payload, ensure_ascii=False),
                now if action_taken else None,
                project_state["status"],
                str(project_state.get("updated_at") or ""),
                now,
            ),
        )
        if decision_changed or action_taken:
            con.execute(
                """
                INSERT INTO agent_supervisor_events(
                  id,project_id,choice,confidence,risk_score,autonomous,reason_code,
                  state_json,decision_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(uuid.uuid4()),
                    project_state["project_id"],
                    decision.choice,
                    decision.confidence,
                    decision.risk_score,
                    1 if decision.autonomous else 0,
                    decision.reason_code,
                    json.dumps(project_state, ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False),
                    now,
                ),
            )


def _mark_human_review(project_id: str, reason_code: str) -> None:
    with core.db() as con:
        row = con.execute(
            "SELECT status,last_audit_json FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()
        if not row:
            return
        current_status = str(row["status"] or "")
        if current_status in {"ready", "ready_for_payment", "payment_pending"}:
            return
        audit = _read_json(row["last_audit_json"])
        issues = [item for item in (audit.get("issues") or []) if isinstance(item, dict)]
        if not any(str(item.get("code") or "") == "SUPERVISOR_REVIEW_REQUIRED" for item in issues):
            issues.append(
                {
                    "severity": "high",
                    "code": "SUPERVISOR_REVIEW_REQUIRED",
                    "file": "",
                    "message": f"Autonomous recovery stopped safely: {reason_code}. Manual review is required.",
                }
            )
        audit["issues"] = issues
        audit["supervisor_review_required"] = True
        audit["supervisor_reason_code"] = reason_code
        con.execute(
            "UPDATE projects SET status='needs_review',last_audit_json=?,updated_at=? WHERE id=?",
            (json.dumps(audit, ensure_ascii=False), core.now_iso(), project_id),
        )


async def _build_runner(project_id: str) -> None:
    try:
        await core.generate_project(project_id)
    except Exception:
        logger.exception("Supervisor build recovery failed project=%s", project_id)
    finally:
        _active_recovery_tasks.pop(project_id, None)


async def _publish_runner(project_id: str) -> None:
    try:
        await retry_routes._publish_existing(project_id)
    except Exception:
        logger.exception("Supervisor publish recovery failed project=%s", project_id)
    finally:
        _active_recovery_tasks.pop(project_id, None)


def _start_recovery(project_id: str, choice: str) -> bool:
    existing = _active_recovery_tasks.get(project_id)
    if existing and not existing.done():
        return False

    if choice == "retry_build":
        with core.db() as con:
            con.execute(
                "UPDATE projects SET status='queued',updated_at=? WHERE id=?",
                (core.now_iso(), project_id),
            )
        task = asyncio.create_task(_build_runner(project_id))
    elif choice == "retry_publish":
        task = asyncio.create_task(_publish_runner(project_id))
    else:
        return False

    _active_recovery_tasks[project_id] = task
    return True


async def supervisor_tick() -> dict[str, Any]:
    if not SUPERVISOR_ENABLED:
        return {"enabled": False, "examined": 0, "actions": 0}

    if _tick_lock.locked():
        return {"enabled": True, "skipped": "tick_already_running", "examined": 0, "actions": 0}

    async with _tick_lock:
        ensure_supervisor_schema()
        if not _acquire_supervisor_lease():
            return {
                "enabled": True,
                "skipped": "lease_owned_by_another_process",
                "instance_id": PROCESS_INSTANCE_ID[:8],
                "examined": 0,
                "actions": 0,
            }
        runtime = await runtime_health()
        with core.db() as con:
            rows = con.execute(
                """
                SELECT * FROM projects
                ORDER BY updated_at ASC
                LIMIT 1000
                """
            ).fetchall()

        examined = 0
        actions = 0
        decisions: dict[str, int] = {}
        for raw in rows:
            row = dict(raw)
            project_id = str(row["id"])
            supervisor = _supervisor_row(project_id)
            state = _state_from_project(row, supervisor)
            decision = decide(state, runtime)
            examined += 1
            decisions[decision.choice] = decisions.get(decision.choice, 0) + 1

            action_taken = False
            if decision.autonomous and decision.choice in {"retry_build", "retry_publish"}:
                action_taken = _start_recovery(project_id, decision.choice)
                if action_taken:
                    actions += 1
                    logger.warning(
                        "Supervisor recovery project=%s choice=%s reason=%s confidence=%.2f",
                        project_id,
                        decision.choice,
                        decision.reason_code,
                        decision.confidence,
                    )
            elif decision.choice == "human_review":
                _mark_human_review(project_id, decision.reason_code)

            _save_decision(state, supervisor, decision, action_taken=action_taken)

        return {
            "enabled": True,
            "examined": examined,
            "actions": actions,
            "decisions": decisions,
            "runtime": runtime,
            "active_recoveries": list(_active_recovery_tasks),
        }


@core.app.on_event("startup")
async def start_autonomous_supervisor() -> None:
    ensure_supervisor_schema()
    if not SUPERVISOR_ENABLED:
        logger.info("Autonomous supervisor disabled")
        return

    # The base application registers a legacy self-heal job under this same id.
    # Replace it with the bounded typed-decision supervisor once all patches are
    # imported.
    core.scheduler.add_job(
        supervisor_tick,
        "interval",
        seconds=SUPERVISOR_INTERVAL_SECONDS,
        id="self-heal",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    asyncio.create_task(supervisor_tick())
    logger.info(
        "Autonomous supervisor online interval=%ss stale=%ss max_recoveries=%s",
        SUPERVISOR_INTERVAL_SECONDS,
        SUPERVISOR_STALE_SECONDS,
        SUPERVISOR_MAX_RECOVERIES,
    )


@core.app.get("/agent/supervisor")
async def supervisor_status(user_id: str = Depends(core.current_user)):
    del user_id
    ensure_supervisor_schema()
    runtime = await runtime_health()
    with core.db() as con:
        recent = con.execute(
            """
            SELECT project_id,choice,confidence,risk_score,autonomous,reason_code,created_at
            FROM agent_supervisor_events
            ORDER BY created_at DESC
            LIMIT 25
            """
        ).fetchall()
        project_states = con.execute(
            """
            SELECT last_choice,COUNT(*) AS n
            FROM agent_supervisor_state
            GROUP BY last_choice
            """
        ).fetchall()
    return {
        "enabled": SUPERVISOR_ENABLED,
        "mode": "local_typed_decisions",
        "pattern": "state -> typed choice -> bounded action",
        "interval_seconds": SUPERVISOR_INTERVAL_SECONDS,
        "stale_seconds": SUPERVISOR_STALE_SECONDS,
        "queue_stale_seconds": SUPERVISOR_QUEUE_STALE_SECONDS,
        "max_recoveries": SUPERVISOR_MAX_RECOVERIES,
        "cooldown_seconds": SUPERVISOR_COOLDOWN_SECONDS,
        "runtime": runtime,
        "active_recoveries": list(_active_recovery_tasks),
        "decision_counts": {str(row["last_choice"] or "none"): int(row["n"]) for row in project_states},
        "recent": [dict(row) for row in recent],
    }


@core.app.get("/projects/{project_id}/supervisor")
async def project_supervisor_status(project_id: str, user_id: str = Depends(core.current_user)):
    with core.db() as con:
        project = con.execute(
            "SELECT * FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")

    supervisor = _supervisor_row(project_id)
    state = _state_from_project(dict(project), supervisor)
    runtime = await runtime_health()
    decision = decide(state, runtime)
    with core.db() as con:
        recent = con.execute(
            """
            SELECT choice,confidence,risk_score,autonomous,reason_code,created_at
            FROM agent_supervisor_events
            WHERE project_id=?
            ORDER BY created_at DESC
            LIMIT 12
            """,
            (project_id,),
        ).fetchall()
    return {
        "state": state,
        "decision": decision.payload(),
        "supervisor": {
            "recovery_count": int(supervisor.get("recovery_count") or 0),
            "last_action_at": supervisor.get("last_action_at"),
        },
        "recent": [dict(row) for row in recent],
    }


@core.app.post("/agent/supervisor/run")
async def run_supervisor_now(user_id: str = Depends(core.current_user)):
    del user_id
    return await supervisor_tick()
