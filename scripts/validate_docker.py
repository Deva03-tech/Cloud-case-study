"""Tier 3 (Docker-only mode): replay a 10-min burst trace on real Docker PostgreSQL s2
and through the calibrated simulator (10 seeds), compare p95 latency and compute-seconds.

Trace: Workload(rate 12 q/s, burst 120 s, gap 60 s, horizon 600 s), arrivals seed 4242.
Real client: arrivals fired on schedule by a thread pool (64 threads) over 32 pre-opened
connections; latency = completion - scheduled arrival (client queueing included).
Compute-seconds = CPU-seconds consumed: real from the container cgroup (cpu.stat
usage_usec delta), sim from busy server-seconds. (Billed compute is 2 vCPU x 600 s in both
by construction, so it is reported but cannot validate anything.)
Acceptance (frozen): |p95 error| <= 25 %, |compute-seconds error| <= 20 %.
Writes results/validation.json.
"""
from __future__ import annotations

import queue
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import docker_pg  # noqa: E402
from src import common  # noqa: E402
from src.sim import Policy, ServiceModel, Workload, arrivals, simulate  # noqa: E402

WL = Workload(rate_qps=12.0, burst_s=120.0, gap_s=60.0, horizon_s=600.0, first_burst_s=0.0)
TRACE_SEED, SIM_SEEDS, N_CONN = 4242, 10, 32
P95_BAND, CPU_BAND = 0.25, 0.20


def cgroup_cpu_s() -> float:
    out = docker_pg.docker("exec", docker_pg.CFG["container_name"], "cat", "/sys/fs/cgroup/cpu.stat")
    usec = next(int(l.split()[1]) for l in out.splitlines() if l.startswith("usage_usec"))
    return usec / 1e6


def main() -> int:
    sm = ServiceModel.from_file()
    trace = arrivals(WL, sm.queries, np.random.default_rng(TRACE_SEED))
    sql = {q: (common.REPO_ROOT / "sql" / "queries" / f"{q}.sql").read_text(encoding="utf-8")
           for q in sm.queries}
    with common.awake():
        info = docker_pg.start("s2")
        conns: queue.Queue = queue.Queue()
        for _ in range(N_CONN):
            conns.put(psycopg.connect(docker_pg.dsn(), autocommit=True))
        c = conns.get()
        for q in sm.queries:  # warm, as the simulator starts warm
            c.execute(sql[q]).fetchall()
        conns.put(c)
        lat = [None] * len(trace)
        lock = threading.Lock()

        def job(i: int, t_sched: float, q: str, t_base: float):
            conn = conns.get()
            try:
                conn.execute(sql[q]).fetchall()
            finally:
                conns.put(conn)
            with lock:
                lat[i] = time.perf_counter() - (t_base + t_sched)

        cpu0 = cgroup_cpu_s()
        t_base = time.perf_counter() + 1.0
        lateness = []
        with ThreadPoolExecutor(max_workers=64) as ex:
            for i, (t, q) in enumerate(trace):
                d = t_base + t - time.perf_counter()
                if d > 0:
                    time.sleep(d)
                lateness.append(time.perf_counter() - (t_base + t))
                ex.submit(job, i, t, q, t_base)
            rest = t_base + WL.horizon_s - time.perf_counter()
            if rest > 0:
                time.sleep(rest)
        real_cpu = cgroup_cpu_s() - cpu0
        wall = time.perf_counter() - t_base
        while not conns.empty():
            conns.get().close()
        docker_pg.stop()

    real = np.array([x for x in lat if x is not None])
    sims = [simulate(Policy("V-s2", "provisioned", size=2.0), WL, sm, seed, trace=trace)
            for seed in range(SIM_SEEDS)]
    sim_p95 = float(np.mean([s["p95_s"] for s in sims]))
    sim_cpu = float(np.mean([s["busy_server_s"] for s in sims]))
    real_p95 = float(np.percentile(real, 95))
    e_p95 = (sim_p95 - real_p95) / real_p95
    e_cpu = (sim_cpu - real_cpu) / real_cpu
    res = {
        "n_queries": len(trace), "n_completed_real": int(real.size),
        "real": {"p50_s": float(np.percentile(real, 50)), "p95_s": real_p95,
                 "p99_s": float(np.percentile(real, 99)), "cpu_s": real_cpu,
                 "billed_vcpu_s": 2.0 * WL.horizon_s, "wall_s": wall,
                 "dispatch_lateness_p99_s": float(np.percentile(lateness, 99))},
        "sim": {"p50_s_mean": float(np.mean([s["p50_s"] for s in sims])), "p95_s_mean": sim_p95,
                "p95_s_std": float(np.std([s["p95_s"] for s in sims])),
                "p99_s_mean": float(np.mean([s["p99_s"] for s in sims])), "cpu_s_mean": sim_cpu,
                "billed_vcpu_s": sims[0]["compute_vcpu_s"], "per_seed": sims},
        "error": {"p95_rel": e_p95, "compute_s_rel": e_cpu},
        "accept": {"p95": abs(e_p95) <= P95_BAND, "compute_s": abs(e_cpu) <= CPU_BAND},
        "real_latencies_s": [round(x, 5) for x in real.tolist()],
        "container": info,
    }
    res["accept"]["overall"] = res["accept"]["p95"] and res["accept"]["compute_s"]
    common.write_result("validation", res, settings={
        "mode": "Docker-only: sim vs real Docker s2 replay (owner Tier 3 fallback)",
        "workload": WL.__dict__, "trace_seed": TRACE_SEED, "sim_seeds": SIM_SEEDS,
        "connections": N_CONN, "threads": 64, "bands": {"p95": P95_BAND, "compute_s": CPU_BAND},
        "compute_s_definition": "CPU-seconds consumed (cgroup usage_usec) vs sim busy server-seconds"})
    print(f"real p95 {real_p95:.4f}s sim {sim_p95:.4f}s err {e_p95:+.1%} | cpu real {real_cpu:.1f}s "
          f"sim {sim_cpu:.1f}s err {e_cpu:+.1%} | accept {res['accept']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
