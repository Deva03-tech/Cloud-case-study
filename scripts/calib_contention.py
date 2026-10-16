"""Tier 6B concurrency calibration -> results/calib_contention.json.

Per size: cold restart once (docker_pg.cold), 1 warm-up pass of the 8 queries, then a
closed loop at concurrency n in {1, 2, 4, 8} for DURATION_S each: n threads, one
connection each, each thread repeatedly runs a query drawn uniformly from the 8 (seeded).
Records every query's latency, start/end time, errors (class name) and the container's
cgroup CPU-seconds per level.

Fit (only on this file): slowdown model  latency_q(n) = base_q * max(1, a * n / c),
base_q = median latency of query q at n = 1, c = vCPUs; a by least squares on the
per-(q, n) median ratios. Also cpu_per_base = CPU-seconds / sum(base_q of completed
queries), the CPU consumed per second of uncontended service (parallel workers).
  python scripts/calib_contention.py --sizes s2 [s1 s4]
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
import threading
import time
from pathlib import Path

import numpy as np
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import docker_pg  # noqa: E402
from scripts.validate_docker import cgroup_cpu_s  # noqa: E402
from src import common  # noqa: E402

QUERIES = ["q01", "q03", "q04", "q05", "q06", "q10", "q12", "q14"]
LEVELS = [1, 2, 4, 8]
DURATION_S = 120.0
SQL = {q: (common.REPO_ROOT / "sql" / "queries" / f"{q}.sql").read_text(encoding="utf-8") for q in QUERIES}


def closed_loop(n: int, seed: int) -> dict:
    recs, errs, lock = [], [], threading.Lock()
    stop_at = time.perf_counter() + DURATION_S
    t_base = time.perf_counter()

    def worker(i: int):
        rng = random.Random(seed * 100 + i)
        with psycopg.connect(docker_pg.dsn(), autocommit=True) as conn:
            conn.execute("SET statement_timeout = '60s'")
            while time.perf_counter() < stop_at:
                q = rng.choice(QUERIES)
                t0 = time.perf_counter()
                try:
                    conn.execute(SQL[q]).fetchall()
                    t1 = time.perf_counter()
                    with lock:
                        recs.append((q, round(t0 - t_base, 4), round(t1 - t0, 5)))
                except Exception as e:
                    with lock:
                        errs.append({"query": q, "t": round(t0 - t_base, 3), "error": type(e).__name__})

    cpu0 = cgroup_cpu_s()
    ths = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    cpu = cgroup_cpu_s() - cpu0
    wall = time.perf_counter() - t_base
    return {"n": n, "wall_s": round(wall, 2), "cpu_s": round(cpu, 3), "completed": len(recs),
            "errors": errs, "records": [{"q": q, "t": t, "lat": l} for q, t, l in recs]}


def fit(size_data: dict, c: float) -> dict:
    lv = {L["n"]: L for L in size_data["levels"]}
    base = {q: statistics.median([r["lat"] for r in lv[1]["records"] if r["q"] == q]) for q in QUERIES}
    pts = []  # (n, q, median ratio)
    for n, L in lv.items():
        for q in QUERIES:
            xs = [r["lat"] for r in L["records"] if r["q"] == q]
            if xs:
                pts.append((n, q, statistics.median(xs) / base[q]))
    n_arr = np.array([p[0] for p in pts], float)
    y = np.array([p[2] for p in pts])
    grid = np.linspace(0.05, 3.0, 2951)
    sse = [float(np.sum((y - np.maximum(1, a * n_arr / c)) ** 2)) for a in grid]
    a = float(grid[int(np.argmin(sse))])
    pred = np.maximum(1, a * n_arr / c)
    r2 = 1 - float(np.sum((y - pred) ** 2)) / float(np.sum((y - y.mean()) ** 2))
    resid = {int(n): {"mean_ratio": float(np.mean(y[n_arr == n])),
                      "mean_pred": float(np.mean(pred[n_arr == n])),
                      "mean_resid": float(np.mean(y[n_arr == n] - pred[n_arr == n]))} for n in LEVELS}
    cpu_per_base = {}
    for n, L in lv.items():
        sb = sum(base[r["q"]] for r in L["records"])
        cpu_per_base[int(n)] = L["cpu_s"] / sb if sb else float("nan")
    return {"model": "latency = base_q * max(1, a * n / c)", "a": a, "r2": r2, "c": c,
            "base_q_s": base, "points": [{"n": p[0], "q": p[1], "ratio": p[2]} for p in pts],
            "residuals_by_n": resid, "cpu_per_base_by_n": cpu_per_base,
            "cpu_per_base": float(np.median(list(cpu_per_base.values())))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", nargs="+", default=["s2"])
    args = ap.parse_args()
    out = {}
    with common.awake():
        for size in args.sizes:
            info = docker_pg.start(size)
            ready = docker_pg.cold()
            with psycopg.connect(docker_pg.dsn(), autocommit=True) as conn:
                for q in QUERIES:
                    conn.execute(SQL[q]).fetchall()
            levels = []
            for n in LEVELS:
                L = closed_loop(n, seed=hash(size) % 1000 + n)
                levels.append(L)
                print(f"{size} n={n}: {L['completed']} queries, {len(L['errors'])} errors, "
                      f"CPU {L['cpu_s']:.1f}s in {L['wall_s']:.0f}s", flush=True)
            out[size] = {**info, "cold_ready_s": round(ready, 3), "levels": levels}
            out[size]["fit"] = fit(out[size], docker_pg.CFG["sizes"][size]["cpus"])
            f = out[size]["fit"]
            print(f"{size} fit a={f['a']:.3f} R2={f['r2']:.3f} cpu_per_base={f['cpu_per_base']:.2f}", flush=True)
        docker_pg.stop()
    common.write_result("calib_contention", out, settings={
        "levels": LEVELS, "duration_s": DURATION_S, "queries": QUERIES, "sizes": args.sizes,
        "loop": "closed, one connection per thread, uniform query choice",
        "cold": "docker_pg.cold() once per size, then one warm-up pass", "statement_timeout": "60s"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
