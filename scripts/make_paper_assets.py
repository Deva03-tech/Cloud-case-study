"""Generate paper/tables/t01..t11.tex and paper/refs.bib from results/ and configs/ (no hand-typed numbers).

Tables mirror RESULTS.md Tables 1-11 (scripts/make_results_md.py). Price-page access dates
come from configs/prices.yaml; other web references use the date the repo pinned them.
  python scripts/make_paper_assets.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import common  # noqa: E402

R = common.RESULTS_DIR
PAPER = common.REPO_ROOT / "paper"
TAB = PAPER / "tables"
POL = ["P-peak", "P-mean", "P-sched", "S-default", "S-tuned", "S-floor", "S-prewarm"]


def j(name: str) -> dict:
    return json.loads((R / f"{name}.json").read_text(encoding="utf-8"))


def esc(x) -> str:
    s = str(x)
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("_", r"\_"), ("#", r"\#"),
                 ("$", r"\$"), ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\^{}"),
                 ("ρ", r"$\rho$"), ("τ", r"$\tau$"), ("≤", r"$\le$"), ("−", "-"), ("–", "--"), ("÷", "/")):
        s = s.replace(a, b)
    return s


def fmt(v, nd=4) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        if v != v:
            return "--"
        return f"{v:.{nd}g}" if abs(v) >= 1e4 else f"{round(v, nd)}"
    return esc(v)


def write_table(name: str, df: pd.DataFrame, caption: str, label: str, size: str = r"\footnotesize",
                nd: int = 4) -> None:
    cols = list(df.columns)
    align = "".join("r" if pd.api.types.is_numeric_dtype(df[c]) and df[c].dtype != bool else "l" for c in cols)
    lines = [r"\begin{table}[htbp]", r"\centering", size, r"\caption{" + caption + "}", r"\label{" + label + "}",
             r"\setlength{\tabcolsep}{3pt}", r"\begin{tabular}{" + align + "}", r"\toprule",
             " & ".join(r"\textbf{" + esc(c) + "}" for c in cols) + r" \\", r"\midrule"]
    for _, row in df.iterrows():
        lines.append(" & ".join(fmt(v, nd) for v in row.tolist()) + r" \\")
    lines += [r"\botrule", r"\end{tabular}", r"\end{table}", ""]
    (TAB / f"{name}.tex").write_text("\n".join(lines), encoding="utf-8")


def src(*files: str) -> str:
    return " Source: " + ", ".join(r"\texttt{" + esc(f) + "}" for f in files) + "."


def main() -> int:
    TAB.mkdir(parents=True, exist_ok=True)
    # T1 calibration
    c = j("calib_docker")["data"]
    rows = []
    for q in sorted(c["s1"]["queries"]):
        r = {"query": q.upper()}
        for s in ("s1", "s2", "s4"):
            qq = c[s]["queries"][q]
            r[f"{s} warm"] = qq["warm"]["median_s"]
            r[f"{s} p95"] = qq["warm"]["p95_s"]
            r[f"{s} cold"] = qq["cold_first_query"]["median_s"]
        rows.append(r)
    write_table("t01_calibration", pd.DataFrame(rows),
                "Docker PostgreSQL calibration (seconds): warm median, warm p95 and cold first-query median per "
                "query at 1/2/4 vCPU (s1/s2/s4)." + src("results/calib_docker.json"), "tab:calib")
    # T2 sweep v1
    sw = j("sweep")["data"]
    df = pd.read_parquet(R / "sweep.parquet")
    df = df[~df.aux]
    g = df.groupby(["intensity", "gap", "policy"]).agg(
        p95=("p95_s", "mean"), p99=("p99_s", "mean"), cost1k=("cost_per_1k_usd", "mean"),
        vcpu_s=("compute_vcpu_s", "mean"), cold=("cold_starts", "mean"), meets_p95=("meets_p95", "mean")).reset_index()
    g["policy"] = pd.Categorical(g.policy, POL)
    g = g.sort_values(["intensity", "gap", "policy"])
    g["policy"] = g.policy.astype(str)
    write_table("t02_sweep_v1", g, f"Synthetic burst sweep, sim v1 (means over 10 seeds; latency not validated). "
                f"p95 target {sw['p95_target_s']} s." + src("results/sweep.parquet", "results/sweep.json"),
                "tab:sweepv1", size=r"\tiny\renewcommand{\arraystretch}{0.85}")
    # T3 validation v1
    v = j("validation")["data"]
    t3 = pd.DataFrame([
        {"metric": "p95 latency (s)", "real": v["real"]["p95_s"], "sim v1": v["sim"]["p95_s_mean"],
         "error": f"{v['error']['p95_rel']:+.1%}", "pass": v["accept"]["p95"]},
        {"metric": "CPU-seconds", "real": v["real"]["cpu_s"], "sim v1": v["sim"]["cpu_s_mean"],
         "error": f"{v['error']['compute_s_rel']:+.1%}", "pass": v["accept"]["compute_s"]}])
    write_table("t03_validation_v1", t3, "Validation v1: sim v1 vs a real 10-min Docker s2 replay (trace seed 4242); "
                "frozen bands 25\\% (p95) and 20\\% (CPU-s)." + src("results/validation.json"), "tab:valv1")
    # T4 redset v1
    rs = j("redset_sweep")
    t = rs["meta"]["settings"]["trace"]
    d4 = pd.DataFrame(rs["data"]["summary_mean"])
    d4["policy"] = pd.Categorical(d4.policy, POL)
    d4 = d4.sort_values("policy")
    d4["policy"] = d4.policy.astype(str)
    write_table("t04_redset_v1", d4, f"Redset replay, sim v1 (instance {t['instance_id']}, {t['day']}, "
                f"{t['n_queries']} queries; means over 10 seeds; latency not validated)."
                + src("results/redset_sweep.json", "results/redset_trace.json"), "tab:redsetv1")
    # T5 stats (summary of the file: rows per source)
    st = pd.read_csv(R / "stats.csv")
    t5 = st.groupby("source").agg(rows=("metric", "size"), policies=("policy", "nunique"),
                                  metrics=("metric", "nunique")).reset_index()
    write_table("t05_stats_index", t5, "Statistics file index: mean, std, bootstrap 95\\% CI and Wilcoxon "
                "signed-rank vs P-peak (paired by seed) per source, cell, policy and metric." + src("results/stats.csv"),
                "tab:stats")
    # T6 contention
    cc = j("calib_contention")["data"]
    rows = []
    for size, d in cc.items():
        f = d["fit"]
        for L in d["levels"]:
            r = f["residuals_by_n"][str(L["n"])]
            rows.append({"size": size, "n": L["n"], "completed": L["completed"], "errors": len(L["errors"]),
                         "CPU-s": L["cpu_s"], "ratio": r["mean_ratio"], "pred": r["mean_pred"],
                         "resid": r["mean_resid"]})
        fit = f
    write_table("t06_contention", pd.DataFrame(rows), f"Concurrency calibration (closed loop, 120 s per level) and fit "
                f"latency $= b_q \\max(1, a n / c)$: $a={fit['a']:.3f}$, $R^2={fit['r2']:.3f}$, CPU per base "
                f"second {fit['cpu_per_base']:.3f}." + src("results/calib_contention.json"), "tab:contention", nd=3)
    # T7 validation v2
    v2 = j("validation_v2")
    d = v2["data"]
    rows = [{"sim": ver, "p95 real": d["real"]["p95_s"], "p95 sim": r["p95_s_mean"],
             "p95 err": f"{r['error']['p95_rel']:+.1%}", "CPU-s real": d["real"]["cpu_s"], "CPU-s sim": r["cpu_s_mean"],
             "CPU-s err": f"{r['error']['compute_s_rel']:+.1%}", "pass": r["accept"]["overall"]}
            for ver, r in d["sim"].items()]
    write_table("t07_validation_v2", pd.DataFrame(rows), f"Validation v2 on a new trace (seed "
                f"{v2['meta']['settings']['trace_seed']}); {d['n_errors']} real queries failed (DiskFull)."
                + src("results/validation_v2.json"), "tab:valv2", nd=4)
    # T8 overload
    oc = j("redset_overload_check")["data"]
    m = oc["minute_resolution"]
    t8 = pd.DataFrame([
        ("P-mean size (vCPU) / servers", f"{oc['p_mean_size_vcpu']} / {oc['servers_k']}"),
        ("capacity (q/s)", round(oc["capacity_qps"], 2)), ("rho, day mean", round(oc["rho_day_mean"], 3)),
        (f"rho, peak hour ({oc['peak_hour']})", round(oc["rho_peak_hour"], 3)),
        ("rho, max minute", round(m["rho_max_minute"], 3)), ("minutes with rho > 1", m["minutes_with_rho_gt_1"]),
        ("max fluid backlog (queries)", m["fluid_backlog_max_queries_minute_res"]),
        ("backlog drain (s)", m["fluid_backlog_max_drain_s"]),
        ("queue unbounded in overload minutes", oc["queue_unbounded_during_overload_minutes"]),
        ("sim v1 P-mean p95 (s)", round(oc["sim_v1_p_mean"]["p95_s_mean"], 1))], columns=["quantity", "value"])
    t8["value"] = t8["value"].astype(str)
    write_table("t08_overload", t8, "Redset P-mean overload check." + src("results/redset_overload_check.json"),
                "tab:overload")
    # T9 cost v1 vs v2
    s1 = pd.read_parquet(R / "sweep.parquet")
    s2 = pd.read_parquet(R / "sweep_v2.parquet")
    cols = ["cost_per_1k_usd", "p95_s"]
    m1 = s1[~s1.aux].groupby(["intensity", "gap", "policy"])[cols].mean()
    m2 = s2[~s2.aux & (s2.split == "select")].groupby(["intensity", "gap", "policy"])[cols].mean()
    rows = []
    for (it, gp, pol), r1 in m1.iterrows():
        r2 = m2.loc[(it, gp, pol)]
        rows.append({"intensity": it, "gap": gp, "policy": pol, "cost1k v1": r1.cost_per_1k_usd,
                     "cost1k v2": r2.cost_per_1k_usd,
                     "/P-peak v1": round(r1.cost_per_1k_usd / m1.loc[(it, gp, "P-peak"), "cost_per_1k_usd"], 3),
                     "/P-peak v2": round(r2.cost_per_1k_usd / m2.loc[(it, gp, "P-peak"), "cost_per_1k_usd"], 3),
                     "p95 v2 (NV)": r2.p95_s})
    t9 = pd.DataFrame(rows)
    t9["policy"] = pd.Categorical(t9.policy, POL)
    t9 = t9.sort_values(["intensity", "gap", "policy"])
    t9["policy"] = t9.policy.astype(str)
    write_table("t09_cost_v1_v2", t9, "Cost per 1,000 queries (USD), sim v1 vs sim v2 (headline: v2), seeds 0--9; "
                "/P-peak = ratio to P-peak in the same cell; NV = not validated."
                + src("results/sweep.parquet", "results/sweep_v2.parquet"), "tab:costv1v2", size=r"\tiny\renewcommand{\arraystretch}{0.85}")
    # T10 held-out S-tuned
    sw2 = j("sweep_v2")["data"]
    h = s2[~s2.aux & (s2.split == "eval")].groupby(["intensity", "gap", "policy"])[
        ["cost_per_1k_usd", "p95_s", "meets_p95"]].mean()
    rows = []
    for k, vv in sw2["tuned_tau"].items():
        it, gp = k.split("/")
        rows.append({"cell": k, "tau (s)": int(vv["tau_s"]), "cost1k 0-9": m2.loc[(it, gp, "S-tuned"), "cost_per_1k_usd"],
                     "cost1k 10-19": h.loc[(it, gp, "S-tuned"), "cost_per_1k_usd"],
                     "/P-peak 10-19": round(h.loc[(it, gp, "S-tuned"), "cost_per_1k_usd"]
                                            / h.loc[(it, gp, "P-peak"), "cost_per_1k_usd"], 3),
                     "p95 10-19 (NV)": h.loc[(it, gp, "S-tuned"), "p95_s"]})
    write_table("t10_stuned_heldout", pd.DataFrame(rows), "S-tuned (sim v2): timeout chosen on seeds 0--9, scored on "
                "held-out seeds 10--19." + src("results/sweep_v2.parquet"), "tab:heldout")
    # T11 redset cost v1 vs v2
    r1 = pd.DataFrame(j("redset_sweep")["data"]["summary_mean"]).set_index("policy")
    rr = j("redset_sweep_v2")["data"]
    r2 = pd.DataFrame(rr["summary_mean"]).set_index("policy")
    rows = [{"policy": p, "cost1k v1": r1.loc[p, "cost_per_1k_usd"], "cost1k v2": r2.loc[p, "cost_per_1k_usd"],
             "/P-peak v1": round(r1.loc[p, "cost_per_1k_usd"] / r1.loc["P-peak", "cost_per_1k_usd"], 3),
             "/P-peak v2": round(r2.loc[p, "cost_per_1k_usd"] / r2.loc["P-peak", "cost_per_1k_usd"], 3),
             "p95 v2 (NV)": r2.loc[p, "p95_s"]} for p in POL if p in r2.index]
    write_table("t11_redset_cost_v1_v2", pd.DataFrame(rows), f"Redset cost per 1,000 queries, sim v1 vs sim v2; S-tuned "
                f"$\\tau$ (v2) = {rr['tuned_tau_s']:.0f} s." + src("results/redset_sweep.json",
                                                                    "results/redset_sweep_v2.json"), "tab:redsetcost")

    # refs.bib
    pr = yaml.safe_load((common.REPO_ROOT / "configs" / "prices.yaml").read_text(encoding="utf-8"))
    acc = {s_["url"]: s_["accessed"] for v in pr.values() if isinstance(v, dict) for s_ in v.get("sources", [])}
    pinned = "2026-10-16"  # date the repo pinned/downloaded these (DECISIONS.md)

    def web(key, title, author, url, year="2026", date=None):
        return (f"@misc{{{key},\n  author = {{{author}}},\n  title = {{{title}}},\n  year = {{{year}}},\n"
                f"  url = {{{url}}},\n  note = {{Accessed {date or acc.get(url, pinned)}}}\n}}\n")

    bib = [
        web("tpch", "{TPC Benchmark H} Standard Specification", "{Transaction Processing Performance Council}",
            "https://www.tpc.org/tpch/"),
        "@article{redset,\n  author = {Saxena, Gaurav and Rahman, Mohammad and Chainani, Naresh and Lin, Chunbin and "
        "Caragea, George and Chowdhury, Fahim and Marcus, Ryan and Kraska, Tim and Pandis, Ippokratis and Narayanaswamy, "
        "Balakrishnan},\n  title = {Why {TPC} Is Not Enough: An Analysis of the {Amazon Redshift} Fleet},\n"
        "  journal = {Proceedings of the VLDB Endowment},\n  volume = {17},\n  number = {11},\n  pages = {3694--3706},\n"
        "  year = {2024}\n}\n",
        web("redsetdata", "{Redset}: query metadata from {Amazon Redshift} (dataset, CC BY-NC 4.0)",
            "{Amazon Science}", "https://github.com/amazon-science/redset"),
        web("neonpricing", "{Neon} pricing", "{Neon}", "https://neon.com/pricing"),
        web("auroraprice", "{Amazon Aurora} pricing", "{Amazon Web Services}", "https://aws.amazon.com/rds/aurora/pricing/"),
        web("aurorapause", "Scaling to zero {ACUs} with automatic pause and resume for {Aurora} serverless",
            "{Amazon Web Services}",
            "https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2-auto-pause.html"),
        web("rdsprice", "{Amazon RDS} for {PostgreSQL} pricing", "{Amazon Web Services}",
            "https://aws.amazon.com/rds/postgresql/pricing/"),
        web("vantage", "db.m7g.large pricing and specs (mirror of the {AWS} price list)", "{Vantage}",
            "https://instances.vantage.sh/aws/rds/db.m7g.large"),
        web("simpy", "{SimPy}: discrete event simulation for {Python}, version 4.1.2", "{Team SimPy}",
            "https://simpy.readthedocs.io/"),
        web("postgres16", "{PostgreSQL} 16 documentation", "{The PostgreSQL Global Development Group}",
            "https://www.postgresql.org/docs/16/"),
    ]
    (PAPER / "refs.bib").write_text("\n".join(bib), encoding="utf-8")
    print(f"wrote {len(list(TAB.glob('*.tex')))} tables and paper/refs.bib ({len(bib)} entries)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
