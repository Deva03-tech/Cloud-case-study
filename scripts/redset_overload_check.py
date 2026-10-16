"""Tier 6F: offered load vs capacity for Redset P-mean -> results/redset_overload_check.json.

Uses only results files: results/redset_trace.json (hourly arrival counts), the P-mean size
rule and calibration means from src/sim.py (results/calib_docker.json), and the simulated
outcome in results/redset_sweep.parquet (v1). Utilisation rho = arrival rate x mean
service time of the uniform 8-query mix at capacity c / servers k (sim v1: k = round(c)).
A queue is unbounded over an interval when rho > 1 there; the backlog then grows at
(rate - k / E[S]) queries per second until load drops.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import common  # noqa: E402
from src.sim import ServiceModel, provisioned_mean_size  # noqa: E402
from scripts.run_redset import TraceWorkload, select_day  # noqa: E402


def main() -> int:
    tr = json.loads((common.RESULTS_DIR / "redset_trace.json").read_text(encoding="utf-8"))["data"]
    hours = tr["hourly_counts"]
    sm = ServiceModel.from_file()
    wl = TraceWorkload(rate_qps=0.0, horizon_s=86400.0, n=tr["n_queries"])
    c = provisioned_mean_size(wl, sm)
    k = max(1, round(c))
    es = sm.mix_mean(c)
    mu = k / es  # service capacity, queries per second
    day_rate = tr["n_queries"] / 86400.0
    per_hour = []
    backlog = 0.0
    for h, n in enumerate(hours):
        lam = n / 3600.0
        rho = lam * es / k
        backlog = max(0.0, backlog + (lam - mu) * 3600.0)
        per_hour.append({"hour": h, "arrivals": n, "rate_qps": round(lam, 4), "rho": round(rho, 4),
                         "unbounded_in_hour": rho > 1, "fluid_backlog_end_of_hour": round(backlog, 1)})
    peak = max(per_hour, key=lambda r: r["rho"])
    # minute resolution from the real arrival timestamps (hourly averages hide sub-hour bursts)
    ts, _ = select_day()
    mins = ts.dt.floor("min").value_counts().sort_index()
    rho_min = (mins / 60.0) * es / k
    backlog_m, bmax, over = 0.0, 0.0, 0
    full = rho_min.reindex(pd.date_range(ts.min().floor("D"), periods=1440, freq="min"), fill_value=0)
    for r in full:
        backlog_m = max(0.0, backlog_m + (r - 1.0) * mu * 60.0)
        bmax = max(bmax, backlog_m)
        over += r > 1
    minute = {"rho_max_minute": float(rho_min.max()), "minutes_with_rho_gt_1": int(over),
              "busiest_minute_arrivals": int(mins.max()),
              "fluid_backlog_max_queries_minute_res": round(bmax, 1),
              "fluid_backlog_max_drain_s": round(bmax / mu, 1)}
    rd = pd.read_parquet(common.RESULTS_DIR / "redset_sweep.parquet")
    pm = rd[(rd.policy == "P-mean") & ~rd.aux]
    out = {
        "p_mean_size_vcpu": c, "servers_k": k, "mean_service_s": es, "capacity_qps": mu,
        "day_mean_rate_qps": day_rate, "rho_day_mean": day_rate * es / k,
        "peak_hour": peak["hour"], "rho_peak_hour": peak["rho"],
        "hours_with_rho_gt_1": [r["hour"] for r in per_hour if r["unbounded_in_hour"]],
        "queue_unbounded_during_peak_hour_avg": peak["rho"] > 1,
        "minute_resolution": minute,
        "queue_unbounded_during_overload_minutes": minute["minutes_with_rho_gt_1"] > 0,
        "fluid_backlog_max": max(r["fluid_backlog_end_of_hour"] for r in per_hour),
        "per_hour": per_hour,
        "sim_v1_p_mean": {"p95_s_mean": float(pm.p95_s.mean()), "p99_s_mean": float(pm.p99_s.mean()),
                          "n_unfinished_mean": float(pm.n_unfinished.mean())},
        "interpretation": ("P-mean is sized on the day-mean rate (rho <= 0.7 rule). Hourly averages stay "
                           "below rho = 1, but in minutes with rho > 1 the queue grows without bound until "
                           "load drops; the drain time of that backlog, not service time, sets its p95."),
    }
    common.write_result("redset_overload_check", out, settings={
        "sources": ["results/redset_trace.json", "results/calib_docker.json", "results/redset_sweep.parquet"],
        "model": "sim v1 servers k = round(c); fluid backlog per hour"})
    print(f"P-mean c={c} k={k} E[S]={es:.4f}s capacity {mu:.1f} q/s; rho day {out['rho_day_mean']:.3f}, "
          f"peak hour {peak['hour']} rho {peak['rho']:.2f}; unbounded hours {out['hours_with_rho_gt_1']}; "
          f"minute: {minute}",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
