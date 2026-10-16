"""Tier 4 Redset replay: ONE instance-day of the serverless file -> arrival trace ->
7 policies x 10 seeds through the simulator.

Selection: among instance-days with 2,000-60,000 queries (simulation time budget), the
one with the highest coefficient of variation of hourly query counts (DECISIONS E, cut to
one day). Arrival times are kept; Redset's own queries are not replayed, each arrival is
mapped to one of the 8 TPC-H queries uniformly at random (per seed). P-sched uses an
oracle hourly schedule: 4 vCPU in hours with above-mean counts, 1 vCPU otherwise.
S-tuned picks tau from {60,120,300,600,1800} s as in the sweep.
Outputs: results/redset_trace.json (selection + hourly counts), results/redset_sweep.parquet,
results/redset_sweep.json. Redset: CC BY-NC 4.0, https://github.com/amazon-science/redset
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_sweep import TAUS, p95_target  # noqa: E402
from src import common, cost  # noqa: E402
from src.sim import Policy, ServiceModel, Workload, load_contention, provisioned_mean_size, simulate, with_tau  # noqa: E402

PARQUET = common.REPO_ROOT / "data" / "redset" / "serverless_full.parquet"
SEEDS, MIN_Q, MAX_Q = 10, 2_000, 60_000


@dataclass(frozen=True)
class TraceWorkload(Workload):
    windows: tuple = ()
    n: int = 0

    def bursts(self):
        return list(self.windows)

    def mean_rate(self):
        return self.n / self.horizon_s


def select_day() -> tuple[pd.Series, dict]:
    df = pd.read_parquet(PARQUET, columns=["instance_id", "arrival_timestamp"])
    df["day"] = df.arrival_timestamp.dt.floor("D")
    df["hour"] = df.arrival_timestamp.dt.hour
    hc = df.groupby(["instance_id", "day", "hour"]).size().unstack("hour", fill_value=0)
    hc = hc.reindex(columns=range(24), fill_value=0)
    tot = hc.sum(axis=1)
    hc = hc[(tot >= MIN_Q) & (tot <= MAX_Q)]
    cv = hc.std(axis=1) / hc.mean(axis=1)
    best = cv.idxmax()
    best_cv, cand = float(cv.max()), hc.index
    m = (df.instance_id == best[0]) & (df.day == best[1])
    ts = df.loc[m, "arrival_timestamp"].sort_values()
    hours = ts.dt.hour.value_counts().reindex(range(24), fill_value=0)
    info = {"instance_id": int(best[0]), "day": str(best[1].date()), "n_queries": int(len(ts)),
            "hourly_cv": float(best_cv), "hourly_counts": hours.tolist(),
            "candidates": int(len(cand))}
    return ts, info


_SM = None
_CONT = None


def _init(cont=None):
    global _SM, _CONT
    _SM = ServiceModel.from_file()
    _CONT = cont


def _run(job):
    wl, pol, seed, aux, times = job
    rng = np.random.default_rng(seed + 20_000)
    trace = list(zip(times, rng.choice(_SM.queries, len(times)).tolist()))
    r = simulate(pol, wl, _SM, seed, trace=trace, contention=_CONT)
    c = cost.cost_usd(r["compute_vcpu_s"], pol.price_model)
    return {"trace": "redset-1day", "policy": pol.name, "kind": pol.kind, "seed": seed, "aux": aux,
            "tau_s": pol.tau_s if pol.kind == "serverless" else np.nan, **r, "cost_usd": c,
            "cost_per_1k_usd": cost.per_1k_queries(c, r["n_queries"])}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", choices=["v1", "v2"], default="v1")
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--select-seeds", type=int, default=None)
    args = ap.parse_args()
    sfx = "" if args.sim == "v1" else "_v2"
    cont = load_contention("s2") if args.sim == "v2" else None
    sel_n = args.select_seeds
    t0 = time.perf_counter()
    ts, info = select_day()
    day0 = pd.Timestamp(info["day"])
    times = ((ts - day0).dt.total_seconds()).to_numpy(dtype=float).tolist()
    common.write_result(f"redset_trace{sfx}", info, settings={
        "file": str(PARQUET.name), "min_q": MIN_Q, "max_q": MAX_Q,
        "rule": "max CV of hourly counts among instance-days in range", "license": "CC BY-NC 4.0"})
    hours = np.array(info["hourly_counts"])
    windows = tuple((h * 3600.0, (h + 1) * 3600.0) for h in range(24) if hours[h] > hours.mean())
    wl = TraceWorkload(rate_qps=0.0, horizon_s=86400.0, windows=windows, n=len(times))
    sm = ServiceModel.from_file()
    srv = dict(kind="serverless", price_model="aurora_serverless_v2")
    s_def = Policy("S-default", tau_s=300.0, **srv)
    pols = [(Policy("P-peak", "provisioned", size=4.0), False),
            (Policy("P-mean", "provisioned", size=provisioned_mean_size(wl, sm)), False),
            (Policy("P-sched", "provisioned", size=4.0, scheduled=True, idle_size=1.0), False),
            (s_def, False), (Policy("S-floor", tau_s=float("inf"), **srv), False),
            (Policy("S-prewarm", tau_s=300.0, prewarm=True, **srv), False)]
    pols += [(with_tau(s_def, t, f"S-tau{int(t)}"), True) for t in TAUS if t != 300.0]
    jobs = [(wl, p, s, aux, times) for p, aux in pols for s in range(args.seeds)]
    with common.awake(), Pool(14, initializer=_init, initargs=(cont,)) as pool:
        df = pd.DataFrame(pool.map(_run, jobs))
    df["split"] = "all" if sel_n is None else np.where(df.seed < sel_n, "select", "eval")
    dsel = df if sel_n is None else df[df.split == "select"]
    p95_t, p99_t = p95_target(sm)
    names = {300.0: "S-default", **{t: f"S-tau{int(t)}" for t in TAUS if t != 300.0}}
    stats = {t: dsel[dsel.policy == n][["p95_s", "cost_usd"]].mean() for t, n in names.items()}
    ok = [t for t, s in stats.items() if s.p95_s <= p95_t]
    best = min(ok, key=lambda t: stats[t].cost_usd) if ok else min(stats, key=lambda t: stats[t].p95_s)
    sel = df[df.policy == names[best]].copy()
    sel["policy"], sel["aux"] = "S-tuned", False
    df = pd.concat([df, sel], ignore_index=True)
    df["meets_p95"], df["meets_p99"] = df.p95_s <= p95_t, df.p99_s <= p99_t
    df.to_parquet(common.RESULTS_DIR / f"redset_sweep{sfx}.parquet", index=False)
    dm = df[~df.aux] if sel_n is None else df[~df.aux & (df.split == "select")]
    dh = None if sel_n is None else df[~df.aux & (df.split == "eval")]
    common.write_result(f"redset_sweep{sfx}", {
        "sim_version": args.sim, "contention": cont, "select_seeds": sel_n,
        "summary_heldout_mean": None if dh is None else dh.groupby("policy")[
            ["p95_s", "p99_s", "compute_vcpu_s", "cost_per_1k_usd", "cold_starts"]].mean()
            .round(4).reset_index().to_dict(orient="records"),
        "runs": len(jobs), "elapsed_s": round(time.perf_counter() - t0, 1),
        "tuned_tau_s": best, "tuned_meets_target": bool(ok), "p95_target_s": p95_t,
        "sched_windows_h": [int(a // 3600) for a, _ in windows],
        "summary_mean": dm.groupby("policy")[
            ["p95_s", "p99_s", "compute_vcpu_s", "cost_per_1k_usd", "cold_starts"]].mean()
            .round(4).reset_index().to_dict(orient="records"),
    }, settings={"trace": info, "seeds": args.seeds, "taus_s": TAUS,
                 "query_mapping": "uniform random over 8 TPC-H queries per seed"})
    print(f"redset: instance {info['instance_id']} day {info['day']} n={info['n_queries']} "
          f"cv={info['hourly_cv']:.2f}; tuned tau {best}; {time.perf_counter() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
