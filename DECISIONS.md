# DECISIONS.md — v2 (chat Claude, 2026-10-15 23:40 IST)

Supersedes v1. Every entry: choice · reason · when to revisit. Claude Code appends its own choices under "Claude Code decisions" at the bottom. Nothing here is a result.

## A. Owner decisions (pending)

- **A1 Venue:** recommended **SN Computer Science** (Springer `sn-jnl` class, 150–250-word abstract, subscription route = free, team has used it). arXiv cs.DB preprint optional. Owner: ____
- **A2 Authors and order:** ____ (names known: Devaashish Satram, Sahas Reddy Billa, Rajaneesh Netha Vadlagatta, Somashekar Patnam, Gangadhar Rao, Santhosh Voruganti — confirm spelling and order)
- **A3 Emails, corresponding author:** ____
- **A4 Affiliation:** Department of Information Technology, Chaitanya Bharathi Institute of Technology, Hyderabad, Telangana, India (confirm for all): ____

## B. Research questions

- **RQ1** For which burst duty cycles, idle gaps and intensities is serverless cheaper than provisioned while meeting the p95 target?
- **RQ2** How much of the p95/p99 violation comes from resume (cold-start) penalty, as a function of idle gap versus idle timeout?
- **RQ3** Which idle timeout minimises cost under the p95 target, and how much does a predictive pre-warm policy recover?
- **RQ4** How closely does the calibrated simulator reproduce a real serverless replay (p95 latency, compute-seconds)?

## C. Machine and environment

- Single machine: HP Envy x360 14-fc0100TU, Core Ultra 7 155U (2P + 8E + 2LPE, 14 threads), 32 GB, 1 TB NVMe, Windows 11 Home, Docker Desktop on WSL2.
- `.wslconfig`: memory=20GB, processors=12, swap=4GB. All data on C: (only drive); stop line: C: free < 60 GB.
- Mains power, Best performance mode, HP thermal profile Performance, sleep and hibernate off, lid action none, Windows Update paused.
- **Hybrid-core caveat:** WSL2 vCPUs do not map to fixed P-cores, so container limits are quotas (`--cpus`), not pinned cores. Mitigation: measure while cool, nothing else running, repeats, medians with IQR, Q6 sentinel at start and end of each calibration block (flag if it drifts > 10%). Named in Threats.
- **Cloud timing never overlaps CPU-heavy work** on this one machine: every cloud-timing task takes `logs/exclusive.lock` and refuses to start while another heavy task holds it.

## D. Systems

- **Measured:** Neon Free (serverless PostgreSQL, 0.25–2 CU, scale to zero after 5 min idle), project in the Neon region closest to India; PostgreSQL 16 in Docker at 1, 2, 4 vCPU (2, 4, 8 GB) as the provisioned stand-in.
- **Not used:** Azure SQL serverless (card risk, no time — cut-scope rule).
- **Modelled only (every parameter cited with URL and access date):** Aurora Serverless v2 (ACU scaling, scale to zero, resume), RDS for PostgreSQL on-demand, Neon paid per CU-hour. Prices: us-east-1 list prices; sensitivity ±30%.
- **Offline fallback:** if Neon sign-up or connection is not working by the end of bootstrap, switch to the handover's Docker emulator (pause/stop for scale-to-zero, `docker update` for scaling, vendor-doc cold starts). Validation then becomes simulator vs emulator and is stated as weaker.

## E. Workload

- TPC-H SF 0.1 via DuckDB `tpch` extension → CSV → `COPY`, with PKs and FK indexes. Must stay < 0.4 GB on Neon; else SF 0.05.
- Queries: Q1, Q3, Q4, Q5, Q6, Q10, Q12, Q14 (fixed substitution parameters). Q17/Q20 excluded: pathological plans on vanilla PostgreSQL; stated in the paper.
- Synthetic bursts: on/off process; Poisson arrivals at rate λ during bursts; query type uniform over the subset.
- Redset: serverless file only; 3 instances with the highest coefficient of variation of hourly query counts; 3 consecutive days; arrivals only. CC BY-NC 4.0 cited. First item cut if time runs short.

## F. Calibration (compact, attended build phase; ≈ 50 min, run sequentially)

- Docker: 3 sizes × 8 queries × (1 warm-up + 5 timed reps); 5 cold restarts per size (container restart + page-cache drop). ≈ 20 min.
- Neon: fixed sizes 0.25 / 0.5 / 1 / 2 CU via API autoscaling limits × 8 queries × (1 + 5); 10 forced cold starts via API suspend; scale-up step test (idle → 8 concurrent clients, 8 min, autoscale 0.25–2); RTT 100 × `SELECT 1` before and after each block. ≈ 30 min, ≈ 2 CU-h.
- Client end-to-end time (perf_counter_ns) and, in a separate pass, server time via `EXPLAIN (ANALYZE, TIMING OFF)`.
- **Network:** user-facing latency = server time + RTT. The measured Neon RTT distribution is also added to provisioned latencies, so both are compared as remote cloud databases.
- Every run logs its state: warm/cold, size, restart flag, cache dropped, current CU.
- Confirmatory repeats (5 natural idle-timeout cold starts on Neon, one more Docker pass) run unattended as T4; drift > 10% from the compact calibration is reported as a threat.

## G. Simulator

- SimPy. Serverless: capacity c(t) in CU, controller tick 1 s, scale-up after delay d_up, scale-down after cooldown, idle timeout τ → paused, resume penalty drawn from the measured empirical distribution, per-second billing with a minimum capacity while active.
- Service time: s_q(c) = a_q · c^(−b_q) fitted on the 4 Neon sizes; servers k = max(1, round(2c)). Fit accepted if leave-one-size-out error ≤ 15%; else per-size empirical tables with interpolation.
- Provisioned: k fixed servers, FIFO, Docker-measured service times per size, hourly billing.
- Horizon 12 h simulated per run.

## H. Policies (baselines)

P-peak, P-mean, P-sched (resize at known burst windows); S-default (τ = 5 min), S-tuned (best τ in {1, 2, 5, 10, 30} min), S-floor (never pause, 0.25 CU minimum), S-prewarm (resume ahead of the predicted burst from the last 3 gaps; prediction error logged) — strongest serverless baseline.

## I. Grid, seeds, statistics, targets

- Duty cycle {5, 10, 20, 40}% × idle gap {1, 5, 15, 30, 60} min × intensity {mid, high} = 40 points × 7 policies × 10 seeds = 2,800 runs. Trimmed at launch if the smoke-test ETA does not fit the T1+T2 budget (first cut: intensity {high}).
- Mean ± std and bootstrap 95% CI; paired Wilcoxon signed-rank over seeds for serverless vs best provisioned per point.
- **Latency targets (fixed at launch, before sweeps):** p95 target = 3 × warm median end-to-end latency of the query mix at Neon 1 CU, rounded up to 0.5 s; p99 target = 2 × p95 target.
- Cost: USD per 1,000 queries and USD per 30-day month.

## J. Validation (frozen now)

- Trace (45 min): burst 5 min · gap 2 · burst 5 · gap 8 · burst 5 · gap 15 · burst 5 (warm, just past the 5-min timeout, deep cold). λ from calibration. Neon autoscale 0.25–2 CU. Same trace through the simulator, 10 seeds.
- Metrics: p95 end-to-end latency; compute-seconds from Neon API consumption before/after.
- Acceptable band: |error| ≤ 25% p95, ≤ 20% compute-seconds. Reported whatever it is; outside the band weakens the claims and goes into Threats.

## K. Unattended queue (≈ 02:00–06:00 IST), sequential, each task time-boxed

| Task | What | Budget | Output |
| --- | --- | --- | --- |
| T1 | Main break-even sweep, seeds 0–4 | 50 min | results/sweep_s0-4.json |
| T2 | Same, seeds 5–9 | 50 min | results/sweep_s5-9.json |
| T3 | Validation replay on Neon (exclusive lock) + simulator twin | 55 min | results/validation.json |
| T4 | Confirmatory calibration repeats (exclusive lock) | 30 min | results/calibration_repeat.json |
| T5 | Sensitivity: resume penalty ×0.5/×2, d_up ×0.5/×2, prices ±30%, RTT 0/×2 | 25 min | results/sensitivity.json |
| T6 | Redset replay | 20 min | results/redset.json |
| T7 | Figures (vector PDF) + summary.md sections | 5 min | figures/*.pdf |
| T8 | Release folder, secret scan, commit and push to the private repo | 5 min | release/ |

Time-box rule: a task past its budget saves partial results, marks itself "partial" in STATUS.md and the queue moves on. Sensitivity sits before Redset because reviewers asked for sensitivity last time and the handover names Redset as the first cut.

## L. Guards

- Neon: stop cloud tasks at 60 CU-h used this month.
- Disk: stop if C: free < 60 GB.
- Secrets only in `.env` (git-ignored, Claude Code does not read it). Local Docker DSN is not secret and lives in configs/docker.yaml.
- Secret scan (gitleaks or detect-secrets) before every push.

## Claude Code decisions
<!-- date · choice · reason -->
- 2026-10-16 00:02 IST · Repo lives at C:\dev\cloud-paper, cloned from https://github.com/Deva03-tech/Cloud-case-study (owner-approved) · Original folder C:\Users\Devaashish\OneDrive\Desktop\Cloud is OneDrive-synced; .git, venv, data (TPC-H, Redset) and lock files must not sync. Originals left untouched there.
- 2026-10-16 00:02 IST · Python 3.12.5 instead of 3.11 (owner-approved) · 3.11 not installed; winget per-user install failed; all pinned packages support 3.12. venv at C:\dev\cloud-paper\.venv.
- 2026-10-16 00:02 IST · RUNBOOK.md and P01_scaffold_data_calibration.md not removed with git rm · They exist neither in the clone nor in the original folder, so there is nothing to remove.
- 2026-10-16 00:02 IST · Pre-clone copy kept at C:\dev\_preclone_backup (an empty git init plus the two handover files) · Kept instead of deleted, to be safe; it can be removed once the owner confirms.
- 2026-10-16 00:21 IST · Commits use the existing global git identity (Sahas Reddy Billa, sahasreddybilla07@gmail.com), not Deva03-tech, and no GitHub account linkage is set up (owner instruction) · Owner said everything can be done from Sahas's account and should not be affiliated with any GitHub account.
- 2026-10-16 00:21 IST · Local Docker PostgreSQL on host port 55432 (configs/docker.yaml) · Avoids clashing with any PostgreSQL already on 5432.
- 2026-10-16 00:21 IST · data/ and logs/ are wholly git-ignored; empty tracked dirs carry a .gitkeep · TPC-H CSV and Redset are regenerable/downloadable and too large for git.
- 2026-10-16 00:30 IST · requirements.txt is a full `pip freeze` (all transitive deps pinned), latest versions available on 2026-10-16 · Reproducible install; versions picked by pip, all have cp312 Windows wheels.
- 2026-10-16 00:30 IST · %UserProfile%\.wslconfig created (did not exist): [wsl2] memory=20GB, processors=12, swap=4GB · Per DECISIONS C; requires wsl --shutdown + Docker Desktop restart to apply.
- 2026-10-16 00:32 IST · .env.example renamed NEON_DATABASE_URL → NEON_DSN and dropped NEON_BRANCH_ID · Matches the owner's .env instructions from chat Claude; branch ID is read from the Neon API when needed.
- 2026-10-16 00:32 IST · Power: standby-timeout-ac 0, hibernate-timeout-ac 0, LIDACTION AC = 0 (do nothing), scheme Balanced kept active; no admin needed · Per DECISIONS C. Laptop was on battery when set, so powercfg /overlaysetactive (Best performance) only applied to the DC overlay; AC overlay is still "Best power efficiency" (961cc777…) and must be switched by the owner via Settings › Power mode while plugged in.
- 2026-10-16 00:32 IST · keep_awake uses ES_CONTINUOUS|ES_SYSTEM_REQUIRED only (no ES_DISPLAY_REQUIRED) · Prevents system sleep; display may turn off, which does not affect runs.
- 2026-10-16 00:32 IST · exclusive_lock takes over a lock whose PID is dead (stale) · A crashed unattended task must not block the rest of the queue.
- 2026-10-16 00:34 IST · TPC-H query texts taken from DuckDB tpch_queries() (validation substitution parameters), saved as sql/queries/qNN.sql · Fixed, standard parameters; texts are already PostgreSQL-compatible.
- 2026-10-16 00:34 IST · keys.sql adds PKs and plain indexes on FK columns, no FOREIGN KEY constraints · DECISIONS E asks for PKs and FK indexes; constraints add load time and do not change plans for this query subset.
- 2026-10-16 00:34 IST · Step order changed to 5 → 8 → 9 → 6 → 7 · Docker engine is down pending the owner's restart and .env does not exist yet; Redset download and tests need neither.
- 2026-10-16 00:35 IST · Redset fetched over public HTTPS (https://s3.amazonaws.com/redshift-downloads/redset/serverless/full.parquet, 322,619,676 bytes, Last-Modified 2024-07-17) rather than aws CLI · No AWS CLI or credentials needed; Range requests make it resume-safe. Whole serverless file (308 MB) is "only the serverless file" per step 8; slicing (3 instances × 3 days) happens later in the Redset task.
- 2026-10-16 00:35 IST · pytest.ini sets pythonpath=. so tests import src.common without installing the repo · Simplest setup; no packaging needed.
- 2026-10-16 00:36 IST · Docker: one named volume (cloudpaper-pgdata) shared by all three sizes; container recreated per size with --cpus/--memory (memory-swap = memory); max_parallel_workers_per_gather = vCPU−1 · Load TPC-H once; each size gets parallelism proportional to its quota, as a cloud instance of that size would.
- 2026-10-16 00:36 IST · Cold run = docker stop + drop WSL2 VM page cache (privileged alpine:3.20, echo 3 > /proc/sys/vm/drop_caches) + docker start · Clears both shared_buffers and the OS cache; the VM-wide cache drop is safe because only one size runs at a time.
