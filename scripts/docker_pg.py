"""Local Docker PostgreSQL 16 at 1/2/4 vCPU (provisioned stand-in, DECISIONS D/F).

  python scripts/docker_pg.py start --size s2   # (re)create container at that size
  python scripts/docker_pg.py cold              # restart container + drop page cache
  python scripts/docker_pg.py stop
  python scripts/docker_pg.py smoke             # Q6 at every size -> results/docker_smoke.json

One size at a time. CPU via --cpus quota only (no --cpuset-cpus: WSL2 vCPUs do not
map to fixed P-cores on this hybrid CPU). Data lives in a named volume shared by all
sizes, so the TPC-H load (scripts/load_pg.py --target docker) is done once.
"""
from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import time
from pathlib import Path

import psycopg
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import common  # noqa: E402

CFG = yaml.safe_load((common.REPO_ROOT / "configs" / "docker.yaml").read_text())
VOLUME = "cloudpaper-pgdata"
DROP_CACHES_IMAGE = "alpine:3.20"


def docker(*args: str, check: bool = True) -> str:
    r = subprocess.run(["docker", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def dsn() -> str:
    return (f"host={CFG['host']} port={CFG['port']} user={CFG['user']} "
            f"password={CFG['password']} dbname={CFG['database']}")


def wait_ready(timeout: float = 120) -> float:
    """Block until a real query succeeds; return seconds waited."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        try:
            with psycopg.connect(dsn(), connect_timeout=3) as conn:
                conn.execute("SELECT 1").fetchone()
            return time.perf_counter() - t0
        except psycopg.OperationalError:
            time.sleep(0.25)
    raise TimeoutError("PostgreSQL did not become ready")


def start(size: str) -> dict:
    s = CFG["sizes"][size]
    name = CFG["container_name"]
    docker("rm", "-f", name, check=False)
    docker("volume", "create", VOLUME)
    docker("run", "-d", "--name", name,
           f"--cpus={s['cpus']}", f"--memory={s['memory_gb']}g", f"--memory-swap={s['memory_gb']}g",
           "-p", f"{CFG['port']}:5432",
           "-e", f"POSTGRES_USER={CFG['user']}", "-e", f"POSTGRES_PASSWORD={CFG['password']}",
           "-e", f"POSTGRES_DB={CFG['database']}",
           "-v", f"{VOLUME}:/var/lib/postgresql/data",
           CFG["image"],
           "-c", f"shared_buffers={s['shared_buffers']}",
           "-c", f"max_parallel_workers_per_gather={max(0, s['cpus'] - 1)}",
           "-c", f"max_worker_processes={max(8, s['cpus'] * 2)}")
    ready_s = wait_ready()
    limits = docker("inspect", name, "--format", "{{.HostConfig.NanoCpus}} {{.HostConfig.Memory}}")
    nano, mem = (int(x) for x in limits.split())
    applied = {"cpus": nano / 1e9, "memory_gb": mem / 1024**3}
    if applied["cpus"] != s["cpus"] or round(applied["memory_gb"]) != s["memory_gb"]:
        raise RuntimeError(f"limits not applied: wanted {s}, got {applied}")
    return {"size": size, **s, "applied": applied, "ready_s": round(ready_s, 2)}


def drop_page_cache() -> None:
    """Drop the WSL2 VM page cache (shared by all containers)."""
    docker("run", "--rm", "--privileged", "--pid=host", DROP_CACHES_IMAGE,
           "sh", "-c", "sync; echo 3 > /proc/sys/vm/drop_caches")


def cold() -> float:
    """Restart the container and drop the page cache; return seconds until ready."""
    docker("stop", CFG["container_name"])
    drop_page_cache()
    t0 = time.perf_counter()
    docker("start", CFG["container_name"])
    wait_ready()
    return time.perf_counter() - t0


def stop() -> None:
    docker("rm", "-f", CFG["container_name"], check=False)


def time_query(sql: str) -> float:
    with psycopg.connect(dsn()) as conn:
        t0 = time.perf_counter_ns()
        conn.execute(sql).fetchall()
        return (time.perf_counter_ns() - t0) / 1e9


def smoke(reps: int = 3) -> int:
    q6 = (common.REPO_ROOT / "sql" / "queries" / "q06.sql").read_text(encoding="utf-8")
    out = {}
    for size in CFG["sizes"]:
        info = start(size)
        cold_ready = cold()
        cold_q6 = time_query(q6)
        time_query(q6)  # warm-up
        warm = [time_query(q6) for _ in range(reps)]
        out[size] = {**info, "cold_restart_ready_s": round(cold_ready, 2),
                     "q6_cold_s": round(cold_q6, 4), "q6_warm_s": [round(x, 4) for x in warm],
                     "q6_warm_median_s": round(statistics.median(warm), 4)}
        print(f"{size}: {info['cpus']} vCPU / {info['memory_gb']} GB  Q6 cold {cold_q6:.3f}s, "
              f"warm median {statistics.median(warm):.3f}s  (ready {cold_ready:.1f}s after cold restart)")
    stop()
    image_id = docker("image", "inspect", CFG["image"], "--format", "{{.Id}}")
    common.write_result("docker_smoke", out, settings={
        "image": CFG["image"], "image_id": image_id, "reps": reps, "query": "q06",
        "note": "smoke test only; calibration in Phase 2"})
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("start")
    sp.add_argument("--size", choices=list(CFG["sizes"]), required=True)
    sub.add_parser("cold")
    sub.add_parser("stop")
    sub.add_parser("smoke")
    args = ap.parse_args()
    if args.cmd == "start":
        print(start(args.size))
    elif args.cmd == "cold":
        print(f"ready {cold():.2f}s after cold restart")
    elif args.cmd == "stop":
        stop()
    elif args.cmd == "smoke":
        return smoke()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
