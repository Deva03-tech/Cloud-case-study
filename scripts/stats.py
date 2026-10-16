"""Tier 4 statistics -> results/stats.csv (+ results/stats.json meta).

Per source (sweep, redset), cell and policy, for each metric: mean, std, bootstrap 95% CI
of the mean (10,000 resamples over seeds), and a paired Wilcoxon signed-rank test (by seed)
of each serverless policy vs P-peak. Wilcoxon is two-sided; p = NaN when all differences
are zero (scipy refuses).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import common  # noqa: E402

METRICS = ["p50_s", "p95_s", "p99_s", "compute_vcpu_s", "cost_per_1k_usd", "cold_starts"]
N_BOOT = 10_000


def boot_ci(x: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    if len(x) < 2 or np.all(x == x[0]):
        return float(x.mean()), float(x.mean())
    m = rng.choice(x, (N_BOOT, len(x))).mean(axis=1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def summarise(df: pd.DataFrame, source: str, cell_cols: list[str], rng) -> list[dict]:
    rows = []
    for cell, g in df.groupby(cell_cols):
        cell = cell if isinstance(cell, tuple) else (cell,)
        ref = g[g.policy == "P-peak"].set_index("seed")
        for pol, gp in g.groupby("policy"):
            gp = gp.set_index("seed").sort_index()
            for m in METRICS:
                x = gp[m].to_numpy(dtype=float)
                lo, hi = boot_ci(x, rng)
                w_stat = w_p = np.nan
                if gp.kind.iloc[0] == "serverless":
                    d = gp[m] - ref[m].reindex(gp.index)
                    d = d.dropna().to_numpy(dtype=float)
                    if len(d) and np.any(d != 0):
                        r = st.wilcoxon(d)
                        w_stat, w_p = float(r.statistic), float(r.pvalue)
                rows.append({"source": source, **dict(zip(cell_cols, cell)), "policy": pol,
                             "metric": m, "n": len(x), "mean": x.mean(), "std": x.std(ddof=1),
                             "ci95_lo": lo, "ci95_hi": hi,
                             "wilcoxon_vs_P-peak_stat": w_stat, "wilcoxon_vs_P-peak_p": w_p})
    return rows


def main() -> int:
    rng = np.random.default_rng(0)
    rows = []
    sw = pd.read_parquet(common.RESULTS_DIR / "sweep.parquet")
    rows += summarise(sw[~sw.aux], "sweep", ["intensity", "gap"], rng)
    rp = common.RESULTS_DIR / "redset_sweep.parquet"
    if rp.exists():
        rd = pd.read_parquet(rp)
        rows += summarise(rd[~rd.aux], "redset", ["trace"], rng)
    for name, cells in (("sweep_v2", ["intensity", "gap"]), ("redset_sweep_v2", ["trace"])):
        pv = common.RESULTS_DIR / f"{name}.parquet"
        if pv.exists():
            dv = pd.read_parquet(pv)
            src = name.replace("redset_sweep", "redset")
            rows += summarise(dv[~dv.aux & (dv.split == "select")], src, cells, rng)
            rows += summarise(dv[~dv.aux & (dv.split == "eval")], src + "_heldout", cells, rng)
    out = pd.DataFrame(rows)
    out.to_csv(common.RESULTS_DIR / "stats.csv", index=False, float_format="%.6g")
    common.write_result("stats", {"rows": len(out), "file": "results/stats.csv",
                                  "sources": sorted(out.source.unique().tolist())},
                        settings={"metrics": METRICS, "bootstrap": N_BOOT, "ci": 0.95,
                                  "test": "Wilcoxon signed-rank, two-sided, paired by seed, vs P-peak"})
    print(f"wrote results/stats.csv ({len(out)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
