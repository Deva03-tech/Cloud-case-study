"""Tier 2 sweep: 7 policies x 6 workload cells x 10 seeds (Docker-only + modelled serverless).

Cells: burst rate {1, 4, 12} q/s x idle gap {180, 1200} s; burst 300 s; horizon 3 h.
S-tuned picks, per cell, tau from {60, 120, 300, 600, 1800} s with the lowest mean cost
among taus whose mean p95 meets the target (else the lowest mean p95); the candidate
runs are kept in the parquet with aux=True.

Outputs: results/sweep.parquet (one row per run), results/sweep.json (meta, settings,
targets, tuned tau per cell), results/sweep_latency_seed0.parquet (all latencies, seed 0).
  python scripts/run_sweep.py [--seeds 10] [--workers 14]
  python scripts/run_sweep.py --sim v2 --seeds 20 --select-seeds 10   # Tier 6E -> *_v2 files
With --select-seeds N, S-tuned's tau is chosen on seeds < N ("select") and every policy is
scored on seeds >= N ("eval", held out); the summary uses the eval rows only.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import common, cost  # noqa: E402
from src.sim import Policy, ServiceModel, Workload, load_contention, simulate, standard_policies, with_tau  # noqa: E402

RATES = {"low": 1.0, "mid": 4.0, "high": 12.0}
GAPS = {"short": 180.0, "long": 1200.0}
TAUS = [60.0, 120.0, 300.0, 600.0, 1800.0]
BURST_S, HORIZON_S = 300.0, 10800.0

_SM: ServiceModel | None = None
_CONT: dict | None = None


def p95_target(sm: ServiceModel) -> tuple[float, float]:
    """3 x pooled warm median at 1 vCPU, rounded up to 0.5 s (DECISIONS I); p99 = 2 x p95."""
    pooled = np.concatenate([sm.warm[(q, 1.0)] for q in sm.queries])
    p95 = math.ceil(3 * float(np.median(pooled)) / 0.5) * 0.5
    return p95, 2 * p95


def _init(cont=None):
    global _SM, _CONT
    _SM = ServiceModel.from_file()
    _CONT = cont


def _run(job):
    cell, wl, pol, seed, aux = job
    keep = seed == 0 and not aux
    r = simulate(pol, wl, _SM, seed, keep_latencies=keep, contention=_CONT)
    lat = r.pop("latencies", None)
    c = cost.cost_usd(r["compute_vcpu_s"], pol.price_model)
    row = {**cell, "policy": pol.name, "kind": pol.kind, "seed": seed, "aux": aux,
           "size_vcpu": pol.size if pol.kind == "provisioned" else np.nan,
           "tau_s": pol.tau_s if pol.kind == "serverless" else np.nan,
           "price_model": pol.price_model, **r, "cost_usd": c,
           "cost_per_1k_usd": cost.per_1k_queries(c, r["n_queries"]),
           "cost_rds_rate_usd": cost.cost_usd(r["compute_vcpu_s"], "rds_postgresql"),
           "cost_neon_launch_usd": cost.cost_usd(r["compute_vcpu_s"], "neon_launch")
           if pol.kind == "serverless" else np.nan}
    return row, (lat if keep else None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--sim", choices=["v1", "v2"], default="v1")
    ap.add_argument("--select-seeds", type=int, default=None)
    args = ap.parse_args()
    sfx = "" if args.sim == "v1" else "_v2"
    cont = load_contention("s2") if args.sim == "v2" else None
    sel_n = args.select_seeds
    common.check_free_space()
    sm = ServiceModel.from_file()
    p95_t, p99_t = p95_target(sm)
    jobs = []
    for rname, rate in RATES.items():
        for gname, gap in GAPS.items():
            wl = Workload(rate_qps=rate, burst_s=BURST_S, gap_s=gap, horizon_s=HORIZON_S)
            cell = {"intensity": rname, "rate_qps": rate, "gap": gname, "gap_s": gap}
            base = standard_policies(wl, sm)
            s_def = next(p for p in base if p.name == "S-default")
            pols = [(p, False) for p in base]
            pols += [(with_tau(s_def, t, f"S-tau{int(t)}"), True) for t in TAUS if t != 300.0]
            for p, aux in pols:
                for seed in range(args.seeds):
                    jobs.append((cell, wl, p, seed, aux))
    t0 = time.perf_counter()
    with common.awake(), Pool(args.workers, initializer=_init, initargs=(cont,)) as pool:
        res = pool.map(_run, jobs, chunksize=4)
    elapsed = time.perf_counter() - t0
    df = pd.DataFrame([r for r, _ in res])
    df["split"] = "all" if sel_n is None else np.where(df.seed < sel_n, "select", "eval")

    # S-tuned: select tau per cell, copy those runs as policy "S-tuned"
    tuned, cand_names = {}, {300.0: "S-default", **{t: f"S-tau{int(t)}" for t in TAUS if t != 300.0}}
    extra = []
    for (rn, gn), g in df.groupby(["intensity", "gap"]):
        gs = g if sel_n is None else g[g.split == "select"]
        stats = {t: gs[gs.policy == n][["p95_s", "cost_usd"]].mean() for t, n in cand_names.items()}
        ok = [t for t, s in stats.items() if s.p95_s <= p95_t]
        best = min(ok, key=lambda t: stats[t].cost_usd) if ok else min(stats, key=lambda t: stats[t].p95_s)
        tuned[f"{rn}/{gn}"] = {"tau_s": best, "meets_target": bool(ok)}
        sel = g[g.policy == cand_names[best]].copy()
        sel["policy"], sel["aux"] = "S-tuned", False
        extra.append(sel)
    df = pd.concat([df, *extra], ignore_index=True)
    df["meets_p95"] = df.p95_s <= p95_t
    df["meets_p99"] = df.p99_s <= p99_t
    out = common.RESULTS_DIR / f"sweep{sfx}.parquet"
    df.to_parquet(out, index=False)

    lat_rows = []
    for (row, lat) in res:
        if lat:
            lat_rows.append(pd.DataFrame({"intensity": row["intensity"], "gap": row["gap"],
                                          "policy": row["policy"],
                                          "latency_s": np.asarray(lat, dtype=np.float32)}))
    pd.concat(lat_rows).to_parquet(common.RESULTS_DIR / f"sweep_latency_seed0{sfx}.parquet", index=False)

    main_df = df[~df.aux] if sel_n is None else df[~df.aux & (df.split == "select")]
    held_df = None if sel_n is None else df[~df.aux & (df.split == "eval")]
    common.write_result(f"sweep{sfx}", {
        "runs_total": len(res), "rows_main": len(main_df), "elapsed_s": round(elapsed, 1),
        "p95_target_s": p95_t, "p99_target_s": p99_t, "tuned_tau": tuned,
        "files": [f"results/sweep{sfx}.parquet", f"results/sweep_latency_seed0{sfx}.parquet"],
        "sim_version": args.sim, "contention": cont, "select_seeds": sel_n,
        "summary_scope": "seeds < select_seeds (main grid, S-tuned in-sample)" if sel_n else "all seeds",
        "summary_heldout_mean": None if held_df is None else held_df.groupby(["intensity", "gap", "policy"])[
            ["p95_s", "p99_s", "compute_vcpu_s", "cost_per_1k_usd", "cold_starts"]].mean()
            .round(4).reset_index().to_dict(orient="records"),
        "summary_mean": main_df.groupby(["intensity", "gap", "policy"])[
            ["p95_s", "p99_s", "compute_vcpu_s", "cost_per_1k_usd", "cold_starts"]].mean()
            .round(4).reset_index().to_dict(orient="records"),
    }, settings={
        "mode": "Docker-only + modelled serverless (no .env)", "rates_qps": RATES, "gaps_s": GAPS,
        "burst_s": BURST_S, "horizon_s": HORIZON_S, "seeds": args.seeds, "taus_s": TAUS,
        "policy_params": {p.name: p.__dict__ for p in standard_policies(
            Workload(rate_qps=4.0, gap_s=1200.0), sm)},
        "service_model": {"a": sm.a, "b": sm.b, "calib": "results/calib_docker.json"},
        "rtt_s": 0.0, "workers": args.workers,
        "note": "S-tuned tau selected in-sample on the same 10 seeds; taus < 300 s exceed Aurora's 300 s minimum (Neon Scale allows 60 s)"})
    print(f"{len(res)} runs in {elapsed:.0f}s; p95 target {p95_t}s; tuned {tuned}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
