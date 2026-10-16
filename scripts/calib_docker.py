"""Docker PostgreSQL calibration (Tier 1): 8 TPC-H queries x sizes s1/s2/s4.

Per size: Q6 sentinel (warm median) at start and end; per query: 3 cold runs
(docker_pg.cold(): container stop + WSL2 page-cache drop + start, then a fresh
connection and the first execution) and 1 warm-up + 5 warm reps on one open
connection. Times are client-side perf_counter_ns around execute+fetchall
(local socket, no network RTT). Writes results/calib_docker.json.
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

import numpy as np
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import docker_pg  # noqa: E402
from src import common  # noqa: E402

QUERIES = ["q01", "q03", "q04", "q05", "q06", "q10", "q12", "q14"]
SIZES = ["s1", "s2", "s4"]
COLD_RUNS = 3
WARM_REPS = 5
SQL = {q: (common.REPO_ROOT / "sql" / "queries" / f"{q}.sql").read_text(encoding="utf-8") for q in QUERIES}


def run(conn, sql: str) -> float:
    t0 = time.perf_counter_ns()
    conn.execute(sql).fetchall()
    return (time.perf_counter_ns() - t0) / 1e9


def summ(xs: list[float]) -> dict:
    return {"median_s": round(statistics.median(xs), 5),
            "p95_s": round(float(np.percentile(xs, 95)), 5),
            "min_s": round(min(xs), 5), "max_s": round(max(xs), 5), "n": len(xs)}


def sentinel(conn) -> float:
    run(conn, SQL["q06"])
    return statistics.median(run(conn, SQL["q06"]) for _ in range(5))


def main() -> int:
    common.check_free_space()
    out: dict = {}
    t_all = time.perf_counter()
    with common.awake():
        for size in SIZES:
            info = docker_pg.start(size)
            with psycopg.connect(docker_pg.dsn()) as conn:
                sent_start = sentinel(conn)
            per_q = {}
            for q in QUERIES:
                cold = []
                for _ in range(COLD_RUNS):
                    ready = docker_pg.cold()
                    t0 = time.perf_counter_ns()
                    conn = psycopg.connect(docker_pg.dsn())
                    connect_s = (time.perf_counter_ns() - t0) / 1e9
                    first = run(conn, SQL[q])
                    conn.close()
                    cold.append({"ready_s": round(ready, 4), "connect_s": round(connect_s, 5),
                                 "first_query_s": round(first, 5)})
                with psycopg.connect(docker_pg.dsn()) as conn:
                    run(conn, SQL[q])  # warm-up
                    warm = [round(run(conn, SQL[q]), 5) for _ in range(WARM_REPS)]
                per_q[q] = {"cold_runs": cold,
                            "cold_first_query": summ([c["first_query_s"] for c in cold]),
                            "cold_ready": summ([c["ready_s"] for c in cold]),
                            "warm_s": warm, "warm": summ(warm)}
                print(f"{size} {q}: warm median {per_q[q]['warm']['median_s']:.4f}s, "
                      f"cold first-query median {per_q[q]['cold_first_query']['median_s']:.4f}s", flush=True)
            with psycopg.connect(docker_pg.dsn()) as conn:
                sent_end = sentinel(conn)
            drift = abs(sent_end - sent_start) / sent_start
            out[size] = {**info, "queries": per_q,
                         "sentinel_q6_start_s": round(sent_start, 5), "sentinel_q6_end_s": round(sent_end, 5),
                         "sentinel_drift": round(drift, 4), "sentinel_drift_flag": drift > 0.10}
        docker_pg.stop()
    image_id = docker_pg.docker("image", "inspect", docker_pg.CFG["image"], "--format", "{{.Id}}")
    common.write_result("calib_docker", out, settings={
        "image": docker_pg.CFG["image"], "image_id": image_id, "sizes": docker_pg.CFG["sizes"],
        "queries": QUERIES, "cold_runs": COLD_RUNS, "warm_reps": WARM_REPS, "warmup": 1,
        "cold_definition": "docker stop + drop WSL2 page cache + docker start + new connection; first execution",
        "timing": "client perf_counter_ns around execute+fetchall, local socket (no RTT)",
        "sentinel": "Q6 warm median of 5 at start and end of each size; flag if drift > 10%",
        "elapsed_s": round(time.perf_counter() - t_all, 1)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
