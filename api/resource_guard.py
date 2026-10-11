"""Conservative host RAM admission guard for new Project Visibility jobs.

Never touches Windows processes, existing running builds, or QA thresholds.
Only defers claiming a *new* queued job when the OS reports critical RAM
headroom. Any unsupported/erroring platform is fail-open and observable.
"""
from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class MemorySnapshot:
    total_mb: int
    available_mb: int
    source: str


def _memory_windows() -> MemorySnapshot | None:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return MemorySnapshot(int(status.ullTotalPhys // (1024 * 1024)), int(status.ullAvailPhys // (1024 * 1024)), "windows")


def _memory_linux() -> MemorySnapshot | None:
    values = {}
    with open("/proc/meminfo", encoding="ascii") as f:
        for line in f:
            key, sep, val = line.partition(":")
            if sep and key in {"MemTotal", "MemAvailable"}:
                values[key] = int(val.strip().split()[0]) // 1024
    if "MemTotal" not in values or "MemAvailable" not in values:
        return None
    return MemorySnapshot(values["MemTotal"], values["MemAvailable"], "linux")


def memory_snapshot() -> MemorySnapshot | None:
    try:
        if sys.platform == "win32":
            return _memory_windows()
        if sys.platform.startswith("linux"):
            return _memory_linux()
    except (OSError, ValueError, AttributeError):
        pass
    return None


def resource_guard_enabled() -> bool:
    return os.getenv("PV_RESOURCE_GUARD_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def required_free_mb(total_mb: int) -> int:
    configured = os.getenv("PV_MIN_FREE_RAM_MB", "").strip()
    if configured:
        # No negative threshold or absurd large value; allow explicit tuning.
        try:
            return max(256, min(8192, int(configured)))
        except ValueError:
            pass
    # Lower-capacity machines need less headroom, but never zero.
    return 768 if total_mb <= 12 * 1024 else 1536


def admission_status() -> dict[str, object]:
    enabled = resource_guard_enabled()
    snapshot = memory_snapshot()
    if not snapshot:
        return {
            "enabled": enabled,
            "allow_new_job": True,
            "reason": "memory_unknown",
            "available_mb": None,
            "total_mb": None,
            "required_free_mb": None,
        }
    threshold = required_free_mb(snapshot.total_mb)
    allowed = not enabled or snapshot.available_mb >= threshold
    return {
        "enabled": enabled,
        "allow_new_job": allowed,
        "reason": "ok" if allowed else "insufficient_ram",
        "available_mb": snapshot.available_mb,
        "total_mb": snapshot.total_mb,
        "required_free_mb": threshold,
        "source": snapshot.source,
    }
