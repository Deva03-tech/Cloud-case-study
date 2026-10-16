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
- 2026-10-16 00:53 IST · Docker image pinned to postgres:16.15 (digest sha256:ca0bd484…b641d), PG_VERSION 16.15-1.pgdg13+2 · Latest 16.x on 2026-10-16; digest recorded in configs/docker.yaml and results/docker_smoke.json.
- 2026-10-16 00:53 IST · .env copied from the OneDrive folder into the repo with cp (not opened) but it is 0 bytes there too; owner asked to save it. Step 7 waits on it · Owner instruction: never open or print .env.

### Dell G15 takeover (2026-10-16, new machine)
- 2026-10-16 10:47 IST · Work moved to a Dell G15 5530 (i5-13450HX 10C/16T: 6P+4E, 15.7 GB RAM, RTX 3050 unused, Windows 11 build 26200); spec in results/machine_dell.json · Owner instruction. HP numbers no longer comparable.
- 2026-10-16 10:47 IST · All HP measurements moved to results/hp_bootstrap/ (docker_smoke, load_docker_sf0.1, env_check, tpch_sf0.1_gen, redset_fetch) and are NOT used in the paper · Owner rule; tpch_gen and redset_fetch moved too because they also record the HP as host.
- 2026-10-16 10:50 IST · Repo cloned to D:\dev\Cloud-case-study, venv D:\venvs\cloud-case-study, pip cache and TEMP on D:, Docker Desktop disk already at D:\docker-data, WSL swap at D:\wsl\swap.vhdx · C: has only ~13 GB free; owner asked to use D:.
- 2026-10-16 10:50 IST · Disk stop lines: D: < 20 GB, C: < 3 GB (was C: < 60 GB) · The 60 GB line cannot hold on this machine's C:; data lives on D:.
- 2026-10-16 10:52 IST · .wslconfig: memory=9GB (15.69 GB − 6 GB, rounded down), processors=16, swap=4GB · Owner rule for this machine.
- 2026-10-16 10:52 IST · RAM < 20 GB, so Docker sizes are s1/s2/s4 = 1/2/4 vCPU with 2/3/5 GB (shared_buffers 25%: 512MB/768MB/1280MB), was 2/4/8 GB · Owner rule; s4 at 8 GB would not fit in the 9 GB WSL VM.
- 2026-10-16 10:53 IST · Power: High performance plan (duplicated from the built-in template) active, AC sleep/hibernate/monitor off, lid action none on AC, power-mode overlay Best performance · Owner rule.
- 2026-10-16 10:55 IST · Python 3.13.7 instead of 3.12.5; same pinned requirements.txt (all have cp313 wheels) · 3.12 not installed on the Dell; installing it would cost Tier 0 time. env_check accepts 3.12 or 3.13.
- 2026-10-16 10:58 IST · Result meta now carries host = "Dell G15" (src/common.HOST_LABEL) next to hostname, git commit, UTC and IST · Owner rule: every result file records the host.
- 2026-10-16 10:59 IST · gen_tpch.py falls back to INSTALL tpch FROM 'https://extensions.duckdb.org' · The default http:// extension URL returns HTTP 307 that DuckDB does not follow on this network.
- 2026-10-16 10:59 IST · Commits on the Dell use its existing git identity (Harshith Akella) · The HP's identity belongs to another person; not impersonated.
- 2026-10-16 10:59 IST · PHASE1_REPORT.md named in the takeover prompt does not exist in the repo at aee62b5 · Read HANDOVER, DECISIONS, STATUS instead.
- 2026-10-16 10:54 IST · Docker calibration timing: cold = docker_pg.cold() (stop + WSL2 page-cache drop + start) then a new connection and the first execution; warm = 1 warm-up + 5 reps on one open connection; client perf_counter_ns, local socket, no RTT. Q6 sentinel at start/end per size (no drift > 10%) · Owner Tier 1 spec ("cold = existing docker_pg.py cold").
- 2026-10-16 10:54 IST · .env still absent at the end of Tier 1 → Tier 2 runs in "Docker-only + modelled serverless" mode; Neon load, neon_smoke and calib_neon skipped (no results/calib_neon.json) · Owner rule for this case.
- 2026-10-16 10:59 IST · Simulator (src/sim.py) in Docker-only mode: capacity in vCPU-equivalents (1 vCPU = 1 Neon CU = 2 Aurora ACU, modelled); k = max(1, round(c)) concurrent queries (DECISIONS G said round(2c); Docker sizes are whole vCPUs and PostgreSQL parallel gather already uses c workers per query); service times from calib_docker.json (measured samples at 1/2/4 vCPU, power-law a·c^-b on medians otherwise, b clipped to [0,1]); first query of each type after a resume uses the measured cold/warm ratio · Tier 2 spec; no Neon sizes to fit on.
- 2026-10-16 10:59 IST · Modelled serverless = Aurora Serverless v2: resume 15 s (AWS docs), c_min 0.25 vCPU-eq (0.5 ACU), c_max 4, scale-up doubling every 5 s, scale-down halving after 60 s below target, target = queries in system; scaling constants are assumptions (not measured, not documented by AWS) and go to Threats · No Neon calibration.
- 2026-10-16 10:59 IST · RTT = 0 in the sweep · Neon RTT not measured (no .env); all options compared as local services.
- 2026-10-16 10:59 IST · Workload cells: burst 300 s, rate {1, 4, 12} q/s × idle gap {180, 1200} s (one shorter, one longer than the 300 s default timeout), horizon 3 h, queries uniform over the 8 · Owner: 6 cells; gaps chosen to straddle the timeout.
- 2026-10-16 10:59 IST · Policies: P-peak 4 vCPU; P-mean = smallest of 1/2/4 vCPU with utilisation ≤ 0.7 at the mean rate; P-sched 4 vCPU in bursts, 1 vCPU between, instant resize on a known schedule (real RDS resizes take minutes: Threats); S-default τ 300 s; S-tuned τ from {60,120,300,600,1800} s chosen per cell in-sample (cheapest meeting mean p95 target); S-floor never pause at 0.25; S-prewarm τ 300 s + resume at (last start + mean of last 3 inter-burst intervals − resume − 5 s) · DECISIONS H.
- 2026-10-16 10:59 IST · Targets: p95 = 3 × pooled s1 warm median rounded up to 0.5 s → 0.5 s; p99 = 1.0 s · DECISIONS I rule, with Docker s1 standing in for Neon 1 CU.
- 2026-10-16 10:59 IST · Prices: Aurora $0.12/ACU-h, Neon Launch $0.106/CU-h, RDS $0.084/vCPU-h from db.m7g.large $0.168/h via instances.vantage.sh (AWS page tables did not render) — configs/prices.yaml · RDS figure is a third-party mirror; flagged.
- 2026-10-16 10:59 IST · Queries left in the queue at the 3 h horizon are drained (up to +1 h) for latency; billing stops at the horizon · Keeps backlogged policies' tails visible.
- 2026-10-16 11:12 IST · Tier 3 in Docker-only mode: sim vs a real 10-min Docker s2 replay (rate 12 q/s, burst 120 s, gap 60 s, trace seed 4242; 32 connections). Compute-seconds validated as consumed CPU-seconds (cgroup usage_usec vs sim busy server-seconds), because billed compute is 2 × 600 vCPU-s in both by construction · Owner Tier 3 fallback; billed seconds cannot discriminate.
- 2026-10-16 11:12 IST · VALIDATION FAILED (frozen bands): p95 real 2.336 s vs sim 0.186 s (−92 %), CPU-s real 654.8 vs sim 296.3 (−55 %). Kept as a negative result; the simulator was NOT re-tuned to pass. Diagnosis: calibration measured each query alone, but under 32 concurrent connections in a 2-vCPU quota each query costs ≈ 2.2× its isolated time (parallel-gather workers + CPU contention); the FIFO k = c model has no contention term. Consequence: sweep latencies under load are optimistic, so the latency claims in Table 2 are lower bounds and go into Threats. 96 of 5,089 real queries recorded no latency (worker exceptions not captured — a script flaw, reported) · Owner rule: negative results stay in.
- 2026-10-16 11:12 IST · Validation trace shortened to 10 min (planned 45 min on Neon) and run on Docker, not Neon · Deadline + no .env; logged as a deviation for Threats.
- 2026-10-16 11:14 IST · Redset: one instance-day chosen by max CV of hourly counts among instance-days with 2,000–60,000 queries → instance 1, 2024-04-10, 28,615 queries, CV 4.90 (results/redset_trace.json); arrivals mapped uniformly to the 8 TPC-H queries per seed; P-sched uses an oracle hourly schedule (4 vCPU in above-mean hours); 7 policies × 10 seeds + 4 τ candidates; ran in 14 s · Owner Tier 4 (one day); sweep had finished, so not skipped.
- 2026-10-16 11:14 IST · Stats: per source/cell/policy/metric mean, std, bootstrap 95 % CI (10,000 resamples, seed 0), two-sided Wilcoxon signed-rank vs P-peak paired by seed (NaN when all differences are 0) → results/stats.csv (294 rows) · Owner Tier 4 spec.
- 2026-10-16 11:14 IST · Figures: 3.5-in width, PDF (Type 42 fonts) + PNG 300 dpi, policy colours from the dataviz skill's validated default categorical order, marker shape/line style separate provisioned from serverless; footnotes name coinciding policies. Static paper figures, so no hover layer · Owner Tier 4 spec.
