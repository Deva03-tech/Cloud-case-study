"""Neon smoke test (Phase 1 step 7). Takes the exclusive lock (cloud timing).

1. API: endpoint settings (autoscaling limits, suspend timeout, state, region) and
   project consumption (compute_time_seconds, active_time_seconds) before/after.
2. Q6: 1 warm-up + 3 timed on a warm compute.
3. RTT: 50 x SELECT 1 on one open connection (median, p95).
4. Forced cold start: API suspend, wait for current_state=idle, then time
   connect, first SELECT 1 and first Q6.

Writes results/neon_smoke.json. Never prints the DSN, host or API key.
API docs (read 2026-10-16):
  GET   /projects/{p}/endpoints/{e}          https://api-docs.neon.tech/reference/getprojectendpoint
  POST  /projects/{p}/endpoints/{e}/suspend  https://api-docs.neon.tech/reference/suspendprojectendpoint
  PATCH /projects/{p}/endpoints/{e}          https://api-docs.neon.tech/reference/updateprojectendpoint
  GET   /projects/{p}                        https://api-docs.neon.tech/reference/getproject
"""
from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import psycopg
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import common  # noqa: E402

API = "https://console.neon.tech/api/v2"
KEYS = ("NEON_DSN", "NEON_API_KEY", "NEON_PROJECT_ID", "NEON_ENDPOINT_ID")


class NeonAPI:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {os.environ['NEON_API_KEY']}",
                               "Accept": "application/json"})
        self.p = os.environ["NEON_PROJECT_ID"]
        self.e = os.environ["NEON_ENDPOINT_ID"]

    def _req(self, method: str, path: str, **kw) -> dict:
        r = self.s.request(method, f"{API}{path}", timeout=30, **kw)
        if r.status_code >= 400:  # body may echo ids; status + message field only
            msg = ""
            try:
                msg = r.json().get("message", "")
            except ValueError:
                pass
            raise RuntimeError(f"Neon API {method} {path.split('/')[-1]} -> {r.status_code} {msg}")
        return r.json()

    def endpoint(self) -> dict:
        return self._req("GET", f"/projects/{self.p}/endpoints/{self.e}")["endpoint"]

    def project(self) -> dict:
        return self._req("GET", f"/projects/{self.p}")["project"]

    def suspend(self) -> dict:
        return self._req("POST", f"/projects/{self.p}/endpoints/{self.e}/suspend")


def endpoint_summary(ep: dict) -> dict:
    keys = ["autoscaling_limit_min_cu", "autoscaling_limit_max_cu", "suspend_timeout_seconds",
            "current_state", "region_id", "type", "pg_version", "provisioner"]
    return {k: ep.get(k) for k in keys}


def usage(pr: dict) -> dict:
    keys = ["compute_time_seconds", "active_time_seconds", "consumption_period_start",
            "consumption_period_end", "pg_version", "region_id"]
    return {k: pr.get(k) for k in keys}


def connect():
    return psycopg.connect(os.environ["NEON_DSN"], connect_timeout=60, autocommit=True)


def run(conn, sql: str) -> float:
    t0 = time.perf_counter_ns()
    conn.execute(sql).fetchall()
    return (time.perf_counter_ns() - t0) / 1e9


def main() -> int:
    common.load_env(required=KEYS)
    api = NeonAPI()
    q6 = (common.REPO_ROOT / "sql" / "queries" / "q06.sql").read_text(encoding="utf-8")
    out: dict = {}
    with common.exclusive_lock("neon_smoke"), common.awake():
        out["endpoint_before"] = endpoint_summary(api.endpoint())
        out["usage_before"] = usage(api.project())
        print("endpoint:", out["endpoint_before"])

        with connect() as conn:
            out["server_version"] = conn.execute("SHOW server_version").fetchone()[0]
            out["db_mb"] = round(conn.execute(
                "SELECT pg_database_size(current_database())").fetchone()[0] / 1024**2, 1)
            run(conn, q6)  # warm-up (also wakes the compute if idle)
            warm = [run(conn, q6) for _ in range(3)]
            rtt = [run(conn, "SELECT 1") for _ in range(50)]
        out["q6_warm_s"] = [round(x, 4) for x in warm]
        out["q6_warm_median_s"] = round(statistics.median(warm), 4)
        out["rtt_ms"] = {"n": 50, "median": round(1000 * statistics.median(rtt), 2),
                         "p95": round(1000 * float(np.percentile(rtt, 95)), 2),
                         "min": round(1000 * min(rtt), 2), "max": round(1000 * max(rtt), 2)}
        print(f"Q6 warm median {out['q6_warm_median_s']:.3f}s; RTT median "
              f"{out['rtt_ms']['median']} ms, p95 {out['rtt_ms']['p95']} ms")

        # forced cold start
        t_s = time.perf_counter()
        api.suspend()
        state = None
        while time.perf_counter() - t_s < 120:
            state = api.endpoint().get("current_state")
            if state == "idle":
                break
            time.sleep(1)
        out["suspend_to_idle_s"] = round(time.perf_counter() - t_s, 1)
        out["state_before_cold_query"] = state
        if state != "idle":
            print(f"WARNING: endpoint state {state!r} after 120 s; cold timing may be warm")
        time.sleep(5)  # let the suspend settle
        t0 = time.perf_counter_ns()
        conn = connect()
        t_conn = (time.perf_counter_ns() - t0) / 1e9
        with conn:
            t_sel = run(conn, "SELECT 1")
            t_q6 = run(conn, q6)
            t_q6_after = run(conn, q6)
        out["cold"] = {"connect_s": round(t_conn, 3), "first_select1_s": round(t_sel, 3),
                       "connect_plus_select1_s": round(t_conn + t_sel, 3),
                       "first_q6_s": round(t_q6, 3), "second_q6_s": round(t_q6_after, 3)}
        print(f"cold start: connect {t_conn:.2f}s + SELECT 1 {t_sel:.3f}s; first Q6 {t_q6:.3f}s, "
              f"second Q6 {t_q6_after:.3f}s (suspend→idle {out['suspend_to_idle_s']}s)")

        out["usage_after"] = usage(api.project())
        out["endpoint_after"] = endpoint_summary(api.endpoint())
    b, a = out["usage_before"], out["usage_after"]
    out["compute_time_seconds_delta"] = (a.get("compute_time_seconds") or 0) - (b.get("compute_time_seconds") or 0)
    out["active_time_seconds_delta"] = (a.get("active_time_seconds") or 0) - (b.get("active_time_seconds") or 0)
    print(f"usage this period: compute_time {a.get('compute_time_seconds')} s, "
          f"active_time {a.get('active_time_seconds')} s (counters may lag)")
    common.write_result("neon_smoke", out, settings={
        "q6_reps": 3, "rtt_n": 50, "api_base": API,
        "note": "connect_s includes TLS + compute resume; RTT on an open connection"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
