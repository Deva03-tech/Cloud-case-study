"""Tier 4 figures from results/ files -> figures/*.pdf (vector) + *.png (300 dpi).

Single-column width (3.5 in). Policy colours: fixed categorical order (validated
default palette, light mode); provisioned = square markers / solid lines, serverless =
circle markers / dashed lines, so identity is not colour-alone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import common  # noqa: E402
from src.sim import Policy, ServiceModel, simulate  # noqa: E402

R, F = common.RESULTS_DIR, common.REPO_ROOT / "figures"
POLICIES = ["P-peak", "P-mean", "P-sched", "S-default", "S-tuned", "S-floor", "S-prewarm"]
COLORS = dict(zip(POLICIES, ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]))
W = 3.5
plt.rcParams.update({"font.size": 7, "axes.titlesize": 7.5, "axes.labelsize": 7, "legend.fontsize": 6,
                     "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.grid": True, "grid.color": "#e4e4e0",
                     "grid.linewidth": 0.5, "axes.edgecolor": "#8a8a85", "lines.linewidth": 1.4,
                     "pdf.fonttype": 42, "savefig.bbox": "tight"})


def ls(p: str) -> str:
    return "-" if p.startswith("P") else "--"


def mk(p: str) -> str:
    return "s" if p.startswith("P") else "o"


def save(fig, name: str) -> list[str]:
    F.mkdir(exist_ok=True)
    out = []
    for ext in ("pdf", "png"):
        fig.savefig(F / f"{name}.{ext}", dpi=300)
        out.append(f"figures/{name}.{ext}")
    plt.close(fig)
    return out


def fig_latency_cdf() -> list[str]:
    lat = pd.read_parquet(R / "sweep_latency_seed0.parquet")
    fig, axes = plt.subplots(1, 2, figsize=(W, 1.9), sharey=True)
    for ax, gap in zip(axes, ["short", "long"]):
        d = lat[(lat.intensity == "mid") & (lat.gap == gap)]
        for p in POLICIES:
            x = np.sort(d[d.policy == p].latency_s.to_numpy())
            if len(x):
                ax.plot(x, np.arange(1, len(x) + 1) / len(x), ls(p), color=COLORS[p], label=p, lw=1.1)
        ax.set_xscale("log")
        ax.axvline(0.5, color="#5f5e5a", lw=0.7, ls=":")
        ax.set_title(f"{gap} gap ({'180' if gap == 'short' else '1200'} s)")
        ax.set_xlabel("End-to-end latency (s)")
        ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    axes[0].set_ylabel("CDF (seed 0)")
    axes[0].set_ylim(0.8, 1.001)
    axes[1].legend(loc="lower right", frameon=False, ncol=1)
    fig.suptitle("Mid burst rate (4 q/s), seed 0", fontsize=7.5, y=1.02)
    fig.text(0.5, -0.2, "P-peak and P-sched coincide during bursts (P-sched drawn on top);\n"
             "S-tuned = S-default (short gap) / S-floor (long gap); dotted: p95 target 0.5 s",
             ha="center", va="top", fontsize=5, color="#5f5e5a")
    return save(fig, "latency_cdf")


def fig_pareto() -> list[str]:
    sw = pd.read_parquet(R / "sweep.parquet")
    m = sw[~sw.aux].groupby(["intensity", "gap", "policy"])[["p95_s", "cost_per_1k_usd"]].mean().reset_index()
    fig, axes = plt.subplots(1, 2, figsize=(W, 2.0), sharey=True, sharex=True)
    sizes = {"low": 10, "mid": 22, "high": 40}
    for ax, gap in zip(axes, ["short", "long"]):
        d = m[m.gap == gap]
        for p in POLICIES:
            dp = d[d.policy == p]
            ax.scatter(dp.p95_s, dp.cost_per_1k_usd, s=[sizes[i] for i in dp.intensity], marker=mk(p),
                       color=COLORS[p], edgecolor="white", linewidth=0.6, label=p, zorder=3)
        ax.axvline(0.5, color="#5f5e5a", lw=0.7, ls=":")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_title(f"{gap} idle gap")
        ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    axes[0].set_ylabel("USD per 1,000 queries")
    h, lab = axes[0].get_legend_handles_labels()
    fig.legend(h, lab, loc="upper center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 1.13),
               markerscale=0.8)
    fig.supxlabel("p95 latency (s), mean of 10 seeds", fontsize=7, y=-0.06)
    fig.text(0.5, -0.12, "marker size: burst rate 1 / 4 / 12 q/s; dotted: p95 target 0.5 s; short gap: all "
             "S-policies coincide (no pause; S-prewarm on top); long gap: S-tuned under S-floor", ha="center", va="top", fontsize=5, color="#5f5e5a")
    return save(fig, "cost_vs_p95")


def fig_cold_starts() -> list[str]:
    sw = pd.read_parquet(R / "sweep.parquet")
    srv = ["S-default", "S-tuned", "S-floor", "S-prewarm"]
    d = sw[~sw.aux & sw.policy.isin(srv)].groupby(["gap", "policy"]).cold_starts.agg(["mean", "std"])
    fig, ax = plt.subplots(figsize=(W, 1.8))
    x = np.arange(2)
    w = 0.19
    for i, p in enumerate(srv):
        vals = [d.loc[(g, p), "mean"] for g in ("short", "long")]
        errs = [d.loc[(g, p), "std"] for g in ("short", "long")]
        bars = ax.bar(x + (i - 1.5) * w, vals, w * 0.9, yerr=errs, color=COLORS[p], label=p,
                      error_kw={"lw": 0.6, "capsize": 1.5})
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.15, f"{v:.1f}", ha="center", fontsize=5.5)
    ax.set_xticks(x, ["short gap (180 s)", "long gap (1200 s)"])
    ax.set_ylabel("Cold starts per 3-h run")
    ax.legend(frameon=False, ncol=4, loc="upper left")
    ax.set_ylim(0, max(d["mean"]) * 1.35 + 0.5)
    return save(fig, "cold_starts_by_gap")


def fig_calibration() -> list[str]:
    c = json.loads((R / "calib_docker.json").read_text())["data"]
    qs = sorted(c["s1"]["queries"])
    sizes = [("s1", "1 vCPU", "#2a78d6"), ("s2", "2 vCPU", "#eb6834"), ("s4", "4 vCPU", "#1baf7a")]
    fig, ax = plt.subplots(figsize=(W, 1.9))
    x = np.arange(len(qs))
    w = 0.27
    for i, (s, lab, col) in enumerate(sizes):
        warm = [c[s]["queries"][q]["warm"]["median_s"] * 1000 for q in qs]
        p95 = [c[s]["queries"][q]["warm"]["p95_s"] * 1000 for q in qs]
        cold = [c[s]["queries"][q]["cold_first_query"]["median_s"] * 1000 for q in qs]
        xs = x + (i - 1) * w
        ax.bar(xs, warm, w * 0.9, color=col, label=f"{lab} warm median")
        ax.errorbar(xs, warm, yerr=[np.zeros(len(qs)), np.subtract(p95, warm)], fmt="none",
                    ecolor="#5f5e5a", lw=0.6, capsize=1.2)
        ax.scatter(xs, cold, marker="_", s=30, color="#2b2b28", zorder=4,
                   label="cold first query (median)" if i == 0 else None)
    ax.set_xticks(x, [q.upper().replace("Q0", "Q") for q in qs])
    ax.set_yscale("log")
    ax.set_ylabel("Latency (ms)")
    ax.legend(frameon=False, ncol=2, loc="upper right", fontsize=5.5)
    ax.set_ylim(10, 3000)
    return save(fig, "calibration_docker")


def fig_validation() -> list[str]:
    v = json.loads((R / "validation.json").read_text())
    d, s = v["data"], v["meta"]["settings"]
    from scripts.validate_docker import TRACE_SEED, WL  # same trace definition
    from src.sim import arrivals
    sm = ServiceModel.from_file()
    trace = arrivals(WL, sm.queries, np.random.default_rng(TRACE_SEED))
    sim = simulate(Policy("V-s2", "provisioned", size=2.0), WL, sm, 0, trace=trace, keep_latencies=True)
    real = np.sort(d["real_latencies_s"])
    simx = np.sort(sim["latencies"])
    fig, ax = plt.subplots(figsize=(W, 1.9))
    ax.plot(real, np.arange(1, len(real) + 1) / len(real), "-", color="#2a78d6", label="real Docker s2")
    ax.plot(simx, np.arange(1, len(simx) + 1) / len(simx), "--", color="#eb6834", label="simulator (seed 0)")
    ax.set_xscale("log")
    ax.set_xlabel("End-to-end latency (s)")
    ax.set_ylabel("CDF")
    e = d["error"]
    ax.set_title(f"10-min replay: p95 error {e['p95_rel']:+.0%}, CPU-s error {e['compute_s_rel']:+.0%} "
                 f"(bands 25% / 20%)")
    ax.legend(frameon=False, loc="lower right")
    return save(fig, "validation_sim_vs_real")


def fig_redset() -> list[str]:
    p = R / "redset_sweep.parquet"
    if not p.exists():
        return []
    rd = pd.read_parquet(p)
    m = rd[~rd.aux].groupby("policy")[["p95_s", "cost_per_1k_usd"]].mean()
    fig, ax = plt.subplots(figsize=(W, 1.9))
    for pol in POLICIES:
        if pol in m.index:
            ax.scatter(m.loc[pol, "p95_s"], m.loc[pol, "cost_per_1k_usd"], marker=mk(pol), s=28,
                       color=COLORS[pol], edgecolor="white", linewidth=0.6, label=pol, zorder=3)
    ax.axvline(0.5, color="#5f5e5a", lw=0.7, ls=":")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("p95 latency (s), mean of 10 seeds")
    ax.set_ylabel("USD per 1,000 queries")
    ax.set_title("Redset: one serverless instance-day")
    hidden = [p for p in POLICIES if p in m.index and any(
        q != p and np.isclose(m.loc[p].to_numpy(), m.loc[q].to_numpy(), rtol=0.05).all()
        for q in POLICIES[POLICIES.index(p) + 1:] if q in m.index)]
    if hidden:
        fig.text(0.5, -0.1, "overlapping (within 5%): " + ", ".join(hidden) + " under later policies",
                 ha="center", va="top", fontsize=5, color="#5f5e5a")
    ax.legend(frameon=False, fontsize=5.5, ncol=2, loc="best")
    return save(fig, "redset_cost_vs_p95")


def fig_contention() -> list[str]:
    c = json.loads((R / "calib_contention.json").read_text())["data"]
    fig, ax = plt.subplots(figsize=(W, 1.9))
    for i, (size, d) in enumerate(c.items()):
        f = d["fit"]
        pts = pd.DataFrame(f["points"])
        ax.scatter(pts.n * (1 + 0.04 * (pts.index % 8 - 3.5) / 3.5), pts.ratio, s=10, color="#2a78d6",
                   edgecolor="white", linewidth=0.4, label=f"{size}: median ratio per query", zorder=3)
        n = np.linspace(1, 8, 100)
        ax.plot(n, np.maximum(1, f["a"] * n / f["c"]), "-", color="#eb6834",
                label=f"fit max(1, a·n/c): a={f['a']:.2f}, R²={f['r2']:.2f}")
    ax.set_xscale("log", base=2)
    ax.set_xticks([1, 2, 4, 8], ["1", "2", "4", "8"])
    ax.set_xlabel("Concurrent queries n (closed loop)")
    ax.set_ylabel("Latency / latency at n=1")
    ax.legend(frameon=False, loc="upper left")
    return save(fig, "contention_fit")


def fig_validation_v2() -> list[str]:
    v = json.loads((R / "validation_v2.json").read_text())
    d, st_ = v["data"], v["meta"]["settings"]
    from scripts.validate_docker import WL
    from src.sim import arrivals, load_contention
    sm = ServiceModel.from_file()
    trace = arrivals(WL, sm.queries, np.random.default_rng(st_["trace_seed"]))
    pol = Policy("V-s2", "provisioned", size=2.0)
    s1 = simulate(pol, WL, sm, 0, trace=trace, keep_latencies=True)
    s2 = simulate(pol, WL, sm, 0, trace=trace, keep_latencies=True, contention=load_contention("s2"))
    fig, ax = plt.subplots(figsize=(W, 1.9))
    for x, sty, col, lab in ((d["real_latencies_s"], "-", "#2a78d6", "real Docker s2"),
                             (s1["latencies"], ":", "#eb6834", "sim v1 (seed 0)"),
                             (s2["latencies"], "--", "#1baf7a", "sim v2 (seed 0)")):
        x = np.sort(x)
        ax.plot(x, np.arange(1, len(x) + 1) / len(x), sty, color=col, label=lab)
    ax.set_xscale("log")
    ax.set_xlabel("End-to-end latency (s)")
    ax.set_ylabel("CDF")
    e1, e2 = d["sim"]["v1"]["error"], d["sim"]["v2"]["error"]
    ax.set_title(f"New trace (seed {st_['trace_seed']}): p95 err v1 {e1['p95_rel']:+.0%}, "
                 f"v2 {e2['p95_rel']:+.0%}; CPU-s err v1 {e1['compute_s_rel']:+.0%}, v2 {e2['compute_s_rel']:+.0%}",
                 fontsize=6)
    ax.legend(frameon=False, loc="lower right")
    return save(fig, "validation_v2_sim_vs_real")


def fig_pareto_v2() -> list[str]:
    if not (R / "sweep_v2.parquet").exists():
        return []
    sw = pd.read_parquet(R / "sweep_v2.parquet")
    m = sw[~sw.aux & (sw.split == "select")].groupby(["intensity", "gap", "policy"])[
        ["p95_s", "cost_per_1k_usd"]].mean().reset_index()
    fig, axes = plt.subplots(1, 2, figsize=(W, 2.0), sharey=True, sharex=True)
    sizes = {"low": 10, "mid": 22, "high": 40}
    for ax, gap in zip(axes, ["short", "long"]):
        d = m[m.gap == gap]
        for p in POLICIES:
            dp = d[d.policy == p]
            ax.scatter(dp.p95_s, dp.cost_per_1k_usd, s=[sizes[i] for i in dp.intensity], marker=mk(p),
                       color=COLORS[p], edgecolor="white", linewidth=0.6, label=p, zorder=3)
        ax.axvline(0.5, color="#5f5e5a", lw=0.7, ls=":")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_title(f"{gap} idle gap (sim v2)")
        ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    axes[0].set_ylabel("USD per 1,000 queries")
    h, lab = axes[0].get_legend_handles_labels()
    fig.legend(h, lab, loc="upper center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 1.13), markerscale=0.8)
    fig.supxlabel("p95 latency (s, NOT validated), mean of seeds 0-9", fontsize=7, y=-0.06)
    fig.text(0.5, -0.12, "marker size: burst rate 1 / 4 / 12 q/s; dotted: p95 target 0.5 s; "
             "coinciding policies overlap", ha="center", va="top", fontsize=5, color="#5f5e5a")
    return save(fig, "cost_vs_p95_v2")


def main() -> int:
    made, failed = [], {}
    for fn in (fig_calibration, fig_latency_cdf, fig_pareto, fig_cold_starts, fig_validation, fig_redset,
               fig_contention, fig_validation_v2, fig_pareto_v2):
        try:
            made += fn()
        except Exception as e:  # one broken figure must not block the rest
            failed[fn.__name__] = f"{type(e).__name__}: {e}"
    common.write_result("figures", {"files": made, "failed": failed},
                        settings={"width_in": W, "formats": ["pdf", "png@300dpi"]})
    print("\n".join(made), failed or "", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
