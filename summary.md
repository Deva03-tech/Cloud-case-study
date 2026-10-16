# summary.md

One section per task: settings, outputs, deviations. Numbers live in the result files and in RESULTS.md (generated from them by scripts/make_results_md.py); they are not retyped here.

## Phase 1 (HP Envy, 2026-10-16 00:21–00:54 IST)
Bootstrap on the HP. All its measurements are in results/hp_bootstrap/ and are not used (owner rule, DECISIONS.md).

## Tier 0 – Dell G15 setup
Settings: .wslconfig 9GB/16 CPUs/4GB swap, Docker sizes 2/3/5 GB, High performance plan. Outputs: results/machine_dell.json, results/env_check.json (Neon check fails: no .env).

## Tier 1 – Data + Docker calibration
TPC-H SF 0.1 (results/tpch_sf0.1_gen.json), loaded into postgres:16.15 (results/load_docker_sf0.1.json); 8 queries × s1/s2/s4, 3 cold + 5 warm (results/calib_docker.json, RESULTS.md Table 1). Neon skipped: no .env.

## Tier 2 – Simulator, cost model, sweep
src/sim.py, src/cost.py, configs/prices.yaml, scripts/run_sweep.py; 24 tests pass. 7 policies × 6 cells × 10 seeds (+4 τ candidates): results/sweep.parquet, results/sweep.json, results/sweep_latency_seed0.parquet (RESULTS.md Table 2). Docker-only + modelled serverless mode.

## Tier 3 – Validation
Simulator vs real Docker s2 10-min replay: results/validation.json (RESULTS.md Table 3). FAILED the frozen bands; kept as a negative result. Deviation: Docker instead of Neon, 10 min instead of 45.

## Tier 4 – Stats, Redset, figures
results/stats.csv; Redset one instance-day (results/redset_trace.json, results/redset_sweep.parquet/.json, RESULTS.md Table 4); figures/*.pdf + .png (results/figures.json).

## Tier 5 – Release
RESULTS.md generated from results/; secret scan; final commit and push.

## Tier 6 – Contention fix + revalidation
A: scripts/validate_docker.py logs every query's error class, requires --out and refuses to overwrite (v1 not re-run). B: results/calib_contention.json (s2 only; s1/s4 cut), fit in RESULTS.md Table 6. C: src/sim.py contention term (sim v2; v1 unchanged), 26 tests pass. D: results/validation_v2.json (trace seed 9191), RESULTS.md Table 7: v2 FAILED on p95, passed on CPU-s. E: not run (v2 failed). F: results/redset_overload_check.json (Table 8); stats, figures (contention_fit, validation_v2_sim_vs_real) and RESULTS.md regenerated; headline numbers stay sim v1, unvalidated.

## Tier 7 - v2 cost sweep
results/sweep_v2.*, results/redset_sweep_v2.* (sim v2 unchanged; S-tuned chosen on seeds 0-9, scored on 10-19). RESULTS.md Tables 9-11; cost headlines from v2, latency not validated.
