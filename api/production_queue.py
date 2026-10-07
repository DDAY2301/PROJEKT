"""Persistent production job queue for high-throughput website generation.

SQLite is used as the durable coordination layer so queued/running work survives
process restarts. Multiple worker coroutines (and multiple app processes) can
claim jobs without executing the same project twice. Heavy model calls are
limited separately in api.model_router, so browser QA and Git delivery can
overlap with another project's planning.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sqlite3
import uuid
from typing import Any

from fastapi import Depends

import api.main as core
import api.billing_gate as billing_gate

WORKER_COUNT = max(1, min(12, int(os.getenv("PRODUCTION_WORKERS", "4"))))
POLL_SECONDS = max(0.2, float(os.getenv("PRODUCTION_QUEUE_POLL_SECONDS", "0.8")))
INSTANCE_ID = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
_worker_tasks: list[asyncio.Task] = []
_wake_event: asyncio.Event | None = None


def ensure_schema() -> None:
    with core.db() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS production_jobs (
              project_id TEXT PRIMARY KEY,
              state TEXT NOT NULL,
              priority INTEGER NOT NULL DEFAULT 100,
              attempts INTEGER NOT NULL DEFAULT 0,
              worker_id TEXT,
              last_error TEXT NOT NULL DEFAULT '',
              enqueued_at TEXT NOT NULL,
              started_at TEXT,
              finished_at TEXT,
              updated_at TEXT NOT NULL
            )"""
        )
        columns = {str(row["name"]) for row in con.execute("PRAGMA table_info(production_jobs)").fetchall()}
        if "cancel_requested" not in columns:
            con.execute("ALTER TABLE production_jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0")
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_production_jobs_claim ON production_jobs(state,cancel_requested,priority,enqueued_at)"
        )


def enqueue_project(project_id: str, priority: int = 100) -> bool:
    """Persist one build request. Duplicate queued/running requests are ignored."""
    ensure_schema()
    now = core.now_iso()
    with core.db() as con:
        row = con.execute(
            "SELECT state,cancel_requested FROM production_jobs WHERE project_id=?",
            (project_id,),
        ).fetchone()
        if row and str(row["state"]) in {"queued", "running"}:
            return False
        if row:
            con.execute(
                """UPDATE production_jobs
                   SET state='queued',priority=?,worker_id=NULL,last_error='',
                       cancel_requested=0,enqueued_at=?,started_at=NULL,finished_at=NULL,updated_at=?
                   WHERE project_id=?""",
                (int(priority), now, now, project_id),
            )
        else:
            con.execute(
                """INSERT INTO production_jobs(
                     project_id,state,priority,attempts,worker_id,last_error,
                     cancel_requested,enqueued_at,started_at,finished_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (project_id, "queued", int(priority), 0, None, "", 0, now, None, None, now),
            )
    if _wake_event is not None:
        _wake_event.set()
    return True


def _claim_next(worker_id: str) -> str | None:
    ensure_schema()
    con = core.db()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            """SELECT project_id FROM production_jobs
               WHERE state='queued' AND cancel_requested=0
               ORDER BY priority ASC,enqueued_at ASC
               LIMIT 1"""
        ).fetchone()
        if not row:
            con.commit()
            return None
        project_id = str(row["project_id"])
        now = core.now_iso()
        changed = con.execute(
            """UPDATE production_jobs
               SET state='running',worker_id=?,attempts=attempts+1,
                   started_at=?,updated_at=?
               WHERE project_id=? AND state='queued' AND cancel_requested=0""",
            (worker_id, now, now, project_id),
        ).rowcount
        con.commit()
        return project_id if changed == 1 else None
    except sqlite3.OperationalError:
        con.rollback()
        return None
    finally:
        con.close()


def cancel_requested(project_id: str) -> bool:
    ensure_schema()
    with core.db() as con:
        row = con.execute(
            "SELECT cancel_requested FROM production_jobs WHERE project_id=?",
            (project_id,),
        ).fetchone()
    return bool(row and int(row["cancel_requested"] or 0))


def request_cancel(project_id: str) -> str:
    """Request cooperative cancellation and return the queue state after the request."""
    ensure_schema()
    now = core.now_iso()
    with core.db() as con:
        row = con.execute(
            "SELECT state FROM production_jobs WHERE project_id=?",
            (project_id,),
        ).fetchone()
        if not row:
            return "missing"
        state = str(row["state"] or "")
        if state == "queued":
            con.execute(
                """UPDATE production_jobs
                   SET state='cancelled',cancel_requested=1,finished_at=?,updated_at=?
                   WHERE project_id=?""",
                (now, now, project_id),
            )
            return "cancelled"
        if state == "running":
            con.execute(
                "UPDATE production_jobs SET cancel_requested=1,updated_at=? WHERE project_id=?",
                (now, project_id),
            )
            return "cancel_requested"
        return state


def _finish(project_id: str, state: str, error: str = "") -> None:
    ensure_schema()
    now = core.now_iso()
    with core.db() as con:
        con.execute(
            """UPDATE production_jobs
               SET state=?,last_error=?,finished_at=?,updated_at=?
               WHERE project_id=?""",
            (state, (error or "")[:700], now, now, project_id),
        )


async def _execute(project_id: str, worker_id: str) -> None:
    try:
        if cancel_requested(project_id):
            _finish(project_id, "cancelled")
            with core.db() as con:
                con.execute(
                    "UPDATE projects SET status='cancelled',updated_at=? WHERE id=?",
                    (core.now_iso(), project_id),
                )
            return
        await core.generate_project(project_id)
        with core.db() as con:
            project = con.execute(
                "SELECT status,last_audit_json FROM projects WHERE id=?",
                (project_id,),
            ).fetchone()
        status = str(project["status"] if project else "missing")
        if cancel_requested(project_id) or status == "cancelled":
            _finish(project_id, "cancelled")
        elif status == "failed":
            detail = ""
            if project:
                detail = str(project["last_audit_json"] or "")[:700]
            _finish(project_id, "failed", detail)
        else:
            _finish(project_id, "done")
    except Exception as exc:
        _finish(project_id, "failed", str(exc))
        raise


async def _worker(index: int) -> None:
    worker_id = f"{INSTANCE_ID}-w{index + 1}"
    while True:
        project_id = _claim_next(worker_id)
        if project_id:
            try:
                await _execute(project_id, worker_id)
            except Exception:
                # Project-level runtime already records failure details. Keep the
                # worker alive so one bad build cannot stop production.
                pass
            continue

        if _wake_event is None:
            await asyncio.sleep(POLL_SECONDS)
            continue
        _wake_event.clear()
        try:
            await asyncio.wait_for(_wake_event.wait(), timeout=POLL_SECONDS)
        except asyncio.TimeoutError:
            pass


async def _compat_run_project_once(project_id: str) -> None:
    enqueue_project(project_id)


def recover_interrupted_jobs() -> int:
    """Return abandoned running jobs to the durable queue after a restart."""
    ensure_schema()
    now = core.now_iso()
    with core.db() as con:
        rows = con.execute(
            "SELECT project_id,cancel_requested FROM production_jobs WHERE state='running'"
        ).fetchall()
        for row in rows:
            if int(row["cancel_requested"] or 0):
                con.execute(
                    """UPDATE production_jobs
                       SET state='cancelled',worker_id=NULL,finished_at=?,updated_at=?
                       WHERE project_id=?""",
                    (now, now, str(row["project_id"])),
                )
            else:
                con.execute(
                    """UPDATE production_jobs
                       SET state='queued',worker_id=NULL,started_at=NULL,updated_at=?
                       WHERE project_id=?""",
                    (now, str(row["project_id"])),
                )
        return len(rows)


def queue_snapshot() -> dict[str, Any]:
    ensure_schema()
    with core.db() as con:
        states = con.execute(
            "SELECT state,COUNT(*) AS n FROM production_jobs GROUP BY state"
        ).fetchall()
        running = con.execute(
            """SELECT project_id,worker_id,attempts,cancel_requested,started_at,updated_at
               FROM production_jobs WHERE state='running'
               ORDER BY started_at ASC LIMIT 30"""
        ).fetchall()
        queued = con.execute(
            """SELECT project_id,priority,attempts,cancel_requested,enqueued_at
               FROM production_jobs WHERE state='queued'
               ORDER BY priority ASC,enqueued_at ASC LIMIT 50"""
        ).fetchall()
    return {
        "workers": WORKER_COUNT,
        "instance_id": INSTANCE_ID,
        "states": {str(row["state"]): int(row["n"]) for row in states},
        "running": [dict(row) for row in running],
        "queued": [dict(row) for row in queued],
    }


@core.app.on_event("startup")
async def start_production_workers() -> None:
    global _wake_event
    ensure_schema()
    recover_interrupted_jobs()
    if _wake_event is None:
        _wake_event = asyncio.Event()
    alive = [task for task in _worker_tasks if not task.done()]
    if alive:
        return
    _worker_tasks.clear()
    for index in range(WORKER_COUNT):
        _worker_tasks.append(asyncio.create_task(_worker(index)))
    _wake_event.set()


@core.app.on_event("shutdown")
async def stop_production_workers() -> None:
    for task in list(_worker_tasks):
        task.cancel()
    if _worker_tasks:
        await asyncio.gather(*_worker_tasks, return_exceptions=True)
    _worker_tasks.clear()


@core.app.get("/agent/production-queue")
async def production_queue_status(user_id: str = Depends(core.current_user)):
    del user_id
    return queue_snapshot()


# Existing project creation/build endpoints resolve these module globals at call
# time. Patching them here upgrades all normal launches and restart recovery to
# the persistent queue without changing the public API.
billing_gate.launch_project = enqueue_project
billing_gate._run_project_once = _compat_run_project_once
