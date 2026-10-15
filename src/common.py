"""Shared helpers: .env loading, result writer, STATUS.md updater, keep-awake,
free-space guard and the exclusive lock for cloud-timing tasks (DECISIONS C, L)."""
from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "results"
LOGS_DIR = REPO_ROOT / "logs"
STATUS_PATH = REPO_ROOT / "STATUS.md"
LOCK_PATH = LOGS_DIR / "exclusive.lock"
IST = timezone(timedelta(hours=5, minutes=30), "IST")
MIN_FREE_GB = 60.0


# --- .env -------------------------------------------------------------------

def load_env(required: tuple[str, ...] = ()) -> None:
    """Load REPO_ROOT/.env into os.environ. Never prints values.

    Raises RuntimeError naming (not showing) any required variable that is missing.
    """
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=False)
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"missing in .env: {', '.join(missing)}")


# --- time ---------------------------------------------------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_ist() -> datetime:
    return datetime.now(IST)


# --- result writer ------------------------------------------------------------

def git_commit() -> str:
    """Current HEAD, with '-dirty' if tracked files are modified."""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                               cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
        return head + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def host_info() -> dict:
    return {
        "hostname": platform.node(),
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "cpu": platform.processor(),
        "logical_cpus": os.cpu_count(),
    }


def write_result(name: str, data: dict, settings: dict | None = None,
                 results_dir: Path | None = None) -> Path:
    """Write results/<name>.json with a meta block. Atomic (temp file + replace)."""
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", name):
        raise ValueError(f"bad result name: {name!r}")
    out_dir = results_dir or RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "name": name,
            "git_commit": git_commit(),
            "host": host_info(),
            "utc": now_utc().isoformat(timespec="seconds"),
            "ist": now_ist().isoformat(timespec="seconds"),
            "settings": settings or {},
        },
        "data": data,
    }
    path = out_dir / f"{name}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)
    return path


# --- STATUS.md ------------------------------------------------------------------

STATUS_COLUMNS = ("#", "Task", "Status", "Start", "ETA", "Finished")


def set_next_checkin(text: str, status_path: Path | None = None) -> None:
    """Rewrite line 1 of STATUS.md as 'Next check-in: <text>'."""
    path = status_path or STATUS_PATH
    lines = path.read_text(encoding="utf-8").splitlines()
    line = f"Next check-in: {text}"
    if lines and lines[0].startswith("Next check-in:"):
        lines[0] = line
    else:
        lines.insert(0, line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_task(task_id: str, status_path: Path | None = None, **fields: str) -> None:
    """Update one row of the STATUS.md task table, matched on the '#' column.

    fields use lowercase column names: status, start, eta, finished, task.
    Appends a new row if the id is not present.
    """
    path = status_path or STATUS_PATH
    lines = path.read_text(encoding="utf-8").splitlines()
    keys = [c.lower() for c in STATUS_COLUMNS]
    unknown = set(fields) - set(keys)
    if unknown:
        raise ValueError(f"unknown STATUS columns: {sorted(unknown)}")
    header_idx = next((i for i, l in enumerate(lines)
                       if l.startswith("| # | Task |")), None)
    if header_idx is None:
        raise ValueError("task table not found in STATUS.md")
    i = header_idx + 2
    while i < len(lines) and lines[i].startswith("|"):
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        if cells and cells[0] == str(task_id):
            cells += [""] * (len(keys) - len(cells))
            for k, v in fields.items():
                cells[keys.index(k)] = str(v)
            lines[i] = "| " + " | ".join(cells) + " |"
            break
        i += 1
    else:
        cells = [str(task_id)] + [str(fields.get(k, "")) for k in keys[1:]]
        lines.insert(i, "| " + " | ".join(cells) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- keep-awake -------------------------------------------------------------------

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def keep_awake(on: bool = True) -> bool:
    """Ask Windows not to sleep while this process runs. Returns True on success.
    The display may still turn off. No-op (False) off Windows."""
    if os.name != "nt":
        return False
    flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)
    return bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))


@contextmanager
def awake():
    keep_awake(True)
    try:
        yield
    finally:
        keep_awake(False)


# --- free-space guard ---------------------------------------------------------------

class DiskSpaceError(RuntimeError):
    pass


def free_gb(path: str | Path = "C:\\") -> float:
    return shutil.disk_usage(path).free / 1024**3


def check_free_space(path: str | Path = "C:\\", min_gb: float = MIN_FREE_GB) -> float:
    """Return free GB; raise DiskSpaceError if below min_gb (DECISIONS L stop line)."""
    free = free_gb(path)
    if free < min_gb:
        raise DiskSpaceError(f"{path} free {free:.1f} GB < stop line {min_gb} GB")
    return free


# --- exclusive lock ----------------------------------------------------------------

class LockBusy(RuntimeError):
    pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            k32.GetExitCodeProcess(h, ctypes.byref(code))
            return code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@contextmanager
def exclusive_lock(task: str, lock_path: Path | None = None):
    """Hold logs/exclusive.lock for a cloud-timing (or other heavy) task.

    Raises LockBusy if a live process holds it; a lock left by a dead process is
    taken over (stale). Released on exit, even after an exception.
    """
    path = lock_path or LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    info = {"task": task, "pid": os.getpid(), "ist": now_ist().isoformat(timespec="seconds")}
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                holder = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                holder = {}
            if _pid_alive(int(holder.get("pid", 0))):
                raise LockBusy(f"exclusive lock held by {holder.get('task')} (pid {holder.get('pid')})")
            path.unlink(missing_ok=True)  # stale
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(info, f)
        break
    else:
        raise LockBusy("could not acquire exclusive lock")
    try:
        yield info
    finally:
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("pid") == os.getpid():
                path.unlink()
        except (OSError, ValueError):
            pass


@contextmanager
def timed():
    """Yield a dict whose 'seconds' is filled on exit."""
    t = {"seconds": None}
    t0 = time.perf_counter()
    try:
        yield t
    finally:
        t["seconds"] = time.perf_counter() - t0
