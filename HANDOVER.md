# Serverless vs Provisioned DB Paper: Handover

Oct 15, 2026 · @Harshith

This doc hands a journal-paper project to a fresh chat Claude, which plans it, prompts Claude Code to build and run it, and writes the paper at the end. The owner relays messages between the two. The whole run is a 6–7 hour speedrun, mostly unattended. The doc sets the goal, constraints, workflow and lessons from a previous paper, and leaves the design decisions to you so you can adjust as results come in.

## Start here

The owner is the only link between you (chat Claude) and Claude Code. You never see the machine; Claude Code never sees this chat. Everything you send Claude Code goes as one copy-paste prompt, and everything that comes back arrives as files or Claude Code's report pasted by the owner.

**Roles**

| Who | Owns | Does not do |
| --- | --- | --- |
| Owner (human) | Relaying messages, approvals, account sign-ups, authors, venue choice, final submission | Design decisions unless asked |
| Chat Claude (you) | Brainstorming, design, related work, every prompt to Claude Code, reviewing results, the paper | Inventing or retyping numbers; editing the repo |
| Claude Code (on the laptop) | The repo from first commit to release, all code, runs, result files, figures, `STATUS.md`, `summary.md`, proofreading the final PDF against results | Editing the paper text unless you ask; making design choices silently |

**Phases and hand-offs**

1. **Brainstorm (you, about 20 min).** Read this doc, ask the owner only what you cannot decide (authors, venue, account sign-ups). Write `HANDOVER.md` and `DECISIONS.md` content for the repo: questions, design, systems, workload, metrics, baselines, outputs by filename.
2. **Bootstrap (Claude Code, about 30 min).** Your first prompt: create the repo, commit the two files, set up the environment, generate data, smoke-test the database connections. It reports back.
3. **Build (Claude Code, about 1–1.5 h).** Calibration scripts, simulator, cost model, policies, tests, `run_all.py`. You review its report and fix the design before anything long runs.
4. **Launch (Claude Code, about 15 min).** Smoke-test every task on tiny inputs, then start the unattended queue as plain background processes.
5. **Unattended (about 4 h).** Scripts run and commit results. Nobody needs to watch. Meanwhile you draft the paper skeleton, related work and methods in the venue's template.
6. **Results in (you, about 45 min).** The owner pastes `STATUS.md`, `summary.md` and the result JSON files. You write results and discussion from those files only, and send Claude Code the figure and release prompt.
7. **Verify and release (Claude Code, about 30 min).** Final figures, release folder, secret scan, push, and a proofread of the compiled PDF against the result files. You fix the paper from its list of mismatches.
8. **Submit (owner).** You give the owner the PDF, source zip, metadata (title, abstract, keywords, authors) and the declarations.

The minutes are a guide for a 6–7 hour total. If a phase overruns, cut scope (fewer systems, a smaller grid, skip the Redset replay) rather than skip validation or verification.

**Rules for every prompt you write for Claude Code**

- One prompt per phase, self-contained, copy-paste ready, in a code block so the owner can copy it whole.
- List every output by filename and say exactly what to report back.
- Tell it to commit after every finished step with a clear message, and to keep `STATUS.md` current.
- Tell it to ask, not guess, when a design choice is not covered; for unattended work, to log the choice in `DECISIONS.md` and carry on.
- Ask for information-only replies ("no changes, just report") when you only need facts.
- Never ask it to edit the paper unless you mean to hand it over.

**ETA rule (applies to every Claude Code task, attended or not)**

The owner checks in only at the times Claude Code gives, so every prompt must require these:

- **Before starting a task:** an estimate in minutes and the clock time (IST, UTC+05:30) it should finish, with the next check-in time.
- **After each finished task:** the actual time taken, the ETA for the next task, and the new check-in time.
- **In `STATUS.md` at all times:** a table of tasks with status, start time, ETA, actual finish time, and one line "Next check-in: HH:MM IST" at the top.
- **When the unattended queue launches:** the expected finish time for each task, the queue's overall finish time, and how long one smoke-tested task took (the basis for the estimate).
- **When a task overruns its ETA by more than 50%:** the script logs it in `STATUS.md` with a revised ETA. If a task fails, the queue moves on and the next check-in time stays valid.
- **Estimates come from measured timings** (smoke tests, earlier tasks), not guesses. Round up; a late check-in costs less than an early one that finds nothing done.

You (chat Claude) should also end each prompt to the owner with when to come back: "Paste Claude Code's report when it finishes, about HH:MM IST."

**Rules for what comes back**

- Numbers enter the paper only from result files, never from a chat summary.
- If a report and a file disagree, the file wins; ask Claude Code why.
- If results contradict the plan, change the claims, not the data.

## The brief

Produce a submission-ready journal paper titled, or close to, **"A Simulation-Based Comparative Analysis of Serverless and Provisioned Cloud Relational Databases Under Burst Analytics Workloads"** in about 6–7 hours, at zero cost.

**Hard constraints**

- **Zero spend.** No paid cloud, no paid journal fees. No cloud subscriptions exist yet; any sign-up must not need a card to be charged.
- **6–7 hours total, mostly unattended.** After roughly the first 2 hours, nobody is there to answer questions or click approvals, so long work must run as scripts.
- **Claude Pro** on this account, with no usage spent yet. Pro has rolling usage limits, so Claude Code may pause mid-run. Unattended work must be plain scripts that keep running without Claude.
- **Simulation-based** because of the constraints. A simulation calibrated with free-tier measurements is approved and preferred.
- **Scope is open:** any database engines and any number of them, as long as it fits the time.
- **Authors, order and affiliations** are to be settled with the account owner. Ask them in the brainstorm phase.

**Machines**

| Machine | CPU | RAM | Storage | OS | Use |
| --- | --- | --- | --- | --- | --- |
| HP Envy x360 14-fc0100TU | Intel Core Ultra 7 155U (12 cores: 2 performance, 8 efficient, 2 low-power; 14 threads) | 32 GB LPDDR5x | 1 TB NVMe SSD | Windows 11 Home | Everything: Docker PostgreSQL, simulator, sweeps, unattended runs, repo |

One machine runs the whole project; it has no discrete GPU and none is needed. It is a low-power U-series chip that throttles under long load, and its mixed core types make timings noisy. Run on mains in best-performance mode, take calibration measurements while the chip is cool, repeat measurements, report medians with spread, and run nothing else during measurements. Docker runs through WSL2: give WSL a fixed memory limit in `.wslconfig` and keep Docker's disk on the 1 TB drive.

## Suggested direction

The recommended shape is **measure cheaply, simulate at scale, then validate against one real replay**. Treat everything below as a starting point, not a decision: change any part if a measurement or a constraint says otherwise, and record the change and the reason.

**Why not a pure simulation:** a simulator with invented parameters is the easiest paper for a reviewer to reject. Real measurements of cold start, scaling speed and query service time, even small ones, make it defensible.

**Three layers**

1. **Calibrate** with free real systems: cold-start or resume time, how fast capacity scales up and down, and query service times at each capacity size.
2. **Simulate** cloud-scale behaviour with a discrete-event simulator (for example SimPy).
   - Serverless: capacity units, scale-up and scale-down rates, idle timeout, resume penalty, per-second billing.
   - Provisioned: a fixed-size queue with hourly billing, optionally scheduled resizing.
   - Cost: public list prices, each with its URL and the date it was read.
3. **Validate** by replaying one small burst trace on a real serverless system and comparing measured with simulated p95 latency and compute-seconds. Report the error, whatever it is.

**Candidate systems (verify current terms before relying on them)**

| System | Role | Free route as of 2026-10-15 | Watch out for |
| --- | --- | --- | --- |
| Neon (serverless PostgreSQL) | Real serverless measurements | Free plan: 100 CU-hours per project per month, 0.5 GB storage, autoscaling up to 2 CU, scale to zero after 5 min idle | 0.5 GB cap limits data size; 5-min idle timeout is fixed on Free; network latency from India adds to every query |
| Azure SQL Database serverless | Optional second serverless engine | Free offer: 100,000 vCore-seconds per month per database, 32 GB | Needs an Azure subscription; check whether sign-up needs a card; not compatible with Azure for Students Starter |
| PostgreSQL in Docker on the HP | Stand-in for provisioned instances | Free | Pin CPU and RAM limits per size; run with nothing else heavy on the machine |
| Aurora Serverless v2, RDS PostgreSQL | Modelled only, from docs and price lists | Not run | Every parameter needs a cited source; say clearly they were not measured |

**Fully offline fallback.** If cloud sign-up or network access becomes a problem, emulate serverless in Docker on the same laptop: scale to zero by stopping or pausing the container, autoscale by changing its CPU and memory limits while it runs (`docker update`), and take cold-start and scaling parameters from vendor documentation. This keeps the project free and reproducible, but validation becomes simulator against emulator, which is weaker. Say so in the paper. A middle path is to build offline and spend a short attended slot measuring real Neon cold starts to check the emulator's settings.

**Workloads**

- **Query service times:** TPC-H at a small scale factor (around 0.1 fits Neon's 0.5 GB). Generate data locally with `dbgen` or DuckDB's TPC-H extension.
- **Synthetic bursts:** an on/off arrival process whose burst length, intensity and idle gap are swept.
- **Real arrival patterns:** Redset, Amazon's public Redshift query-metadata trace (three months, 200 serverless and provisioned instances, CC BY-NC 4.0). Download only the slice needed.

**A headline result worth aiming for:** a break-even map across burst duty cycle and idle gap that shows which option is cheaper and whether it meets a p95 or p99 latency target. Likely sub-results are where cold starts break the latency target and which idle timeout minimises cost. Let the data decide what the paper claims.

## Decisions you own

Settle these yourself, write each choice and its reason in a `DECISIONS.md` in the repo, and revisit any of them when results contradict the plan.

**Before any code (brainstorm phase, while the owner is present)**

- [ ] Authors, order, emails, affiliation with city and country, and the corresponding author. Ask the owner.
- [ ] Target venue, then read its author guidelines and submission questionnaire.
- [ ] Research questions phrased so a run can answer them ("for which burst patterns is serverless cheaper at equal p95?"), not slogans.
- [ ] Which real systems to measure. Get every account the owner must create (and any approval click) done now, not during unattended hours.
- [ ] Which provisioned and serverless products to model, and where each parameter comes from.
- [ ] Latency targets (p95, p99) and the cost unit (for example dollars per 1,000 queries and per month).

**Design choices to make and justify**

- [ ] Scale factor and query subset that fit the free storage and compute budgets.
- [ ] Calibration protocol: repetitions per measurement, warm versus cold runs, how network latency is separated from execution time.
- [ ] Simulator model of autoscaling (step size, delay, cooldown) and how it is fitted to measurements.
- [ ] Burst parameter grid and which Redset slice to replay.
- [ ] Baselines and policies to compare (see Reviewer-proofing).
- [ ] Seeds and repetitions, and which statistical summary or test to report.
- [ ] Validation metric and an acceptable error band, set before the validation run.

**Watch during the work**

- [ ] Free-tier meters (Neon CU-hours, Azure vCore-seconds). Stop well before a cap; a paused database mid-run wastes hours.
- [ ] Network latency from India to the cloud region. Measure it, and either subtract it or keep it as part of the user-facing latency, consistently.
- [ ] Docker CPU and RAM limits actually holding, and no background load on the laptop during runs; watch for thermal throttling.
- [ ] Windows sleep, updates and lid-close during unattended hours.
- [ ] Price lists and free-tier terms changing. Save the page date with every number.
- [ ] Any result that looks too clean. Check it against raw logs before writing it up.

## Time plan

The run is a 6–7 hour speedrun: about 2 attended hours to plan, build and launch, about 4 unattended hours of scripted runs, then about 1 hour to write up and verify. Everything that needs a human or an approval happens in the first 2 hours.

| Clock | Mode | Who | Work |
| --- | --- | --- | --- |
| 0:00–0:20 | Attended | You | Brainstorm; settle questions, systems, metrics, outputs; owner creates any accounts |
| 0:20–0:50 | Attended | Claude Code | Repo, environment, data, connection smoke tests |
| 0:50–2:00 | Attended | Claude Code, you reviewing | Calibration, simulator, cost model, policies, tests, `run_all.py`; smoke-test everything; launch |
| 2:00–6:00 | Unattended | Scripts | Calibration repeats, sweeps with seeds, validation replay, Redset replay if time, figures |
| 2:00–6:00 | In parallel | You | Paper skeleton in the venue's template: introduction, related work, methods |
| 6:00–7:00 | Attended | You, then Claude Code | Results and discussion from files; final figures; release; Claude Code proofreads the PDF |

**Pro limits shape the plan.** Claude Code on Pro can hit its usage limit and pause until the window resets. Use it heavily in the first 2 hours to write and test scripts, then launch them as ordinary background processes. Nothing in the unattended block may depend on Claude Code being available.

**Order unattended tasks by value:** the main break-even sweep first, then seeds, then the validation replay, then the Redset replay, then extras. Anything unfinished becomes a stated limitation, not a silent gap.

**Cut scope before cutting checks.** If time runs short, drop the second serverless engine, shrink the grid or skip the Redset replay. Do not drop the validation replay, the seeds or the final proofread.

## Reviewer-proofing

The previous paper's editor questionnaire asked whether the work was compared with recent state-of-the-art methods on benchmark data, "or explained why not". Plan the answer now, not after writing.

**What "state of the art" means for this paper.** There is no single model to beat. Cover it two ways:

1. **Prior studies table.** One row per related paper: systems, workload, burst model, cost model, measured or simulated, validated or not. Your paper's row should differ visibly (for example: burst-focused, calibrated on real free tiers, validated, break-even map). Candidates to check:
   - "Why TPC Is Not Enough: An Analysis of the Amazon Redshift Fleet" (VLDB 2024), which released Redset.
   - Recent trace-driven workload generators such as PBench (arXiv 2025) and Redbench (2026).
   - The Cloud Analytics Benchmark (CAB) by van Renen and Leis.
   - Microsoft's "Moneyball" work on proactive resume for Azure SQL Database serverless.
   - Recent 2024–2026 performance or cost studies of serverless databases, from a fresh search. Open each on the publisher's page before citing it. These titles came from a quick search and have not been verified.
2. **Strong baselines inside the simulator.** A comparison only against weak options will not survive review. For example:
   - Provisioned sized for the peak, for the mean, and with scheduled scaling.
   - Serverless with the default idle timeout, a tuned timeout, and a predictive pre-warm policy as the strongest baseline.

**Desk-rejection triggers from the last submission, and what closes each**

| Trigger | What closes it here |
| --- | --- |
| Wrong template | Write in the venue's own LaTeX class from the start |
| Low-quality figures | Vector PDF from scripts that read result JSON |
| Similarity of 25% or more | Owner runs a similarity check on the final file |
| Over the page limit | Check the venue's limit in hour 0 |
| No recent references | Several 2024–2026 references, each opened on the publisher's page |
| Too few compared methods | Prior studies table plus the baselines above |
| Thin validation | Seeds with mean ± std, a real-replay validation, sensitivity analysis on key parameters |
| Private data not described | Dataset table, calibration protocol, generating scripts in the repo |
| Simulation not credible | Calibration plots, validation error, and a threats section naming every modelled-not-measured parameter |
| Missing declarations | Conflict of interest in the venue's wording, funding (none), data and code links, author contributions, AI-use statement |

**Questions to expect, and where the paper answers them**

- *Why simulate instead of running Aurora and RDS?* Cost constraint, stated plainly; calibration and validation make the simulator trustworthy.
- *Are free-tier numbers representative of production?* Probably not in absolute terms; argue from relative behaviour and run a sensitivity sweep.
- *Is network latency from India inflating results?* Show it was measured and how it was handled.

## Venues

Pick with the owner in hour 0, then build to that venue's checklist. Hybrid journals are free if you choose the standard subscription route rather than open access. Confirm scope, fees and page limits on each journal's site before deciding; nothing here has been rechecked for this paper.

| Venue | Publisher | Fit | Notes |
| --- | --- | --- | --- |
| SN Computer Science | Springer | Broad CS, applied and empirical work | The owner's team has submitted here before (Springer `sn-jnl` LaTeX class, 150–250-word abstract, AI-use disclosure required) |
| Concurrency and Computation: Practice and Experience | Wiley | Cloud and systems performance studies | Check its current template and limits |
| Cluster Computing | Springer | Cloud systems | More selective |
| The Journal of Supercomputing | Springer | Systems and performance | More selective |
| arXiv (cs.DB or cs.DC) | arXiv | Preprint alongside any of the above | Free, gives a citable version immediately; check the journal's preprint policy |

Avoid paid open-access options (for example IEEE Access) given the zero-spend constraint, and avoid any journal you cannot find indexed in Scopus or Web of Science.

## Guardrails and lessons

These held through the owner's previous paper (a LogBERT self-healing study, submitted to SN Computer Science) and are non-negotiable here.

**Guardrails**

- **No invented numbers in anything submitted.** Placeholders are for outlines only. Every number traces to a result file.
- **Results travel as files.** Claude Code writes JSON plus a `summary.md` section per task; the paper never retypes numbers from chat.
- **Claude Code does not edit the paper** unless you decide otherwise; keep one source of truth for the `.tex`.
- **Disclose AI use** in the paper as the venue requires. Do not use tools meant to evade AI detectors.
- **Negative results stay in.** If serverless never wins, or the validation error is large, report it and explain it.
- **No secrets in the public repo.** Connection strings, passwords and API keys go in a `.env` that is git-ignored; run a secret scan before pushing.
- **The owner decides** authorship, venue, funding statements and final approval. Flag risks and leave the choice.

**Lessons that became rules**

| What happened last time | Rule for this paper |
| --- | --- |
| The title promised "proactive" but the data showed otherwise | Let results set the title and claims |
| A causal claim was wrong once raw logs were checked | Check causal claims against raw logs |
| A comparison was confounded by leftover state between runs | Log and reset state that could confound a comparison (here: warm vs cold, cached pages, leftover capacity) |
| A benchmark and repeated runs had to be added late | Map the venue questionnaire in hour 0 and schedule what it needs |
| The system drive nearly filled during long runs | Put caches and data on the drive with space; add a free-space stop line |
| A blurry figure taken from an old PDF | Regenerate every figure from data as vector output |
| Nine wording-versus-data mismatches survived the writer's checks | Have Claude Code proofread the final PDF against its own result files |
| References were out of citation order | Sort the bibliography by script |
| The portal's built PDF dropped authors, then had the wrong order | Read the built PDF's cover page before approving |
| The editorial office asked for city and country per author and a headed Author Contributions section | Put both in the first draft |
| A Windows update interrupted a long run | Pause updates, disable sleep, keep the laptop on mains |

## Templates

Adapt these; fill the angle brackets.

**Kickoff message (the owner sends this to chat Claude with this doc attached)**

```text
The attached handover doc describes a journal paper we will speedrun in 6-7 hours, mostly unattended.
You are the planner and writer. I relay between you and Claude Code on my laptop; I paste your prompts to it and paste its reports and files back to you.
Read the whole doc, ask me only what you cannot decide yourself, then give me the first Claude Code prompt in a code block.
From then on: one copy-paste prompt per phase, outputs listed by filename, and every number in the paper taken from result files.
```

**Repo rules (include in the first Claude Code prompt)**

```text
You own the repo for the whole project.
- Layout: README.md, HANDOVER.md, DECISIONS.md, STATUS.md, summary.md, src/, scripts/, configs/, data/ (git-ignored if large), results/, figures/, paper/, tests/
- .env holds secrets (database URLs, passwords) and is git-ignored; add a .env.example without values.
- Commit after every finished step with a clear message. Never rewrite history.
- STATUS.md: "Next check-in: HH:MM IST" on the first line, then a task table (status, start, ETA, actual finish), errors, free-tier usage, free disk space. Update after every task.
- Before every task, tell me its estimated duration and finish time in IST; after it, the actual time and the next task's ETA.
- DECISIONS.md: every choice you make that the prompt did not specify, with the reason.
- summary.md: one section per task with settings, key numbers and deviations.
- Pin versions (requirements.txt or uv.lock, Docker image tags).
- paper/ holds the LaTeX I send you. Compile it, but change wording only when asked.
```

**Phase prompts to adapt**

1. **Bootstrap:** create the repo and apply the repo rules; commit `HANDOVER.md` and `DECISIONS.md` (content supplied by you); set up Python, Docker and the database containers; generate the data; test every database connection. Report: environment versions, timings, anything that failed.
2. **Build:** calibration scripts, simulator, cost model, policies, unit tests, each with outputs by filename and a test on tiny input. Report: what was built, test output, and every decision it made.
3. **Launch:** write `run_all.py` from the unattended template, smoke-test every task on tiny inputs, then start it in the background so it survives the terminal closing. Report: the exact launch command, the smoke-test output, and how to check progress.
4. **Results report (information only):** "No changes. Report STATUS.md, summary.md and the contents of results/\*.json." The owner pastes the files themselves, not a summary.
5. **Release and proofread:** final figures as vector PDF, compile `paper/`, release folder, secret scan, push to a public repo, then read the compiled PDF against every result file and list each mismatch with page, wording and correct value.

**Unattended-run setup (written and tested while the owner is present)**

```text
Write run_all.py: a queue of tasks in priority order. Each task runs as a normal Python process, not through Claude.

STORAGE: all data, caches and temp files on <DRIVE>. Check free space before each task; stop if <SYSTEM DRIVE> would drop below <X> GB.
FREE TIER: track <Neon CU-hours / Azure vCore-seconds> used; skip cloud tasks once usage passes <limit>.
STATUS: after every task, update STATUS.md ("Next check-in: HH:MM IST" on line 1; per task: status, start, ETA, actual finish, key numbers, errors; revise an ETA when a task overruns by more than 50%) and commit results.
FAILURES: log, skip, continue. No endless retries.
POWER: keep-awake on, on mains, updates paused.

Tasks:
T1 <main break-even sweep>, seeds 0-4 -> results/sweep.json
T2 <validation replay on real serverless> -> results/validation.json
T3 <Redset replay> -> results/redset.json
T4 <sensitivity on key parameters> -> results/sensitivity.json
T5 figures from result JSON as vector PDF -> figures/
T6 release folder: code, configs, README with commands, results, licence; secret scan; commit; do not push

At the end: a summary.md section per task (settings, numbers, deviations) and a final STATUS.md listing what finished, what was skipped and why.
```

Run each task on a tiny input before launching the queue. Expected output of a smoke test: every task writes its JSON, `STATUS.md` lists all tasks as finished, and no errors appear in the log.

**Pre-submission checklist**

- [ ] Every number traced to a result file
- [ ] Every quoted reference opened on the publisher's page
- [ ] References in order of first citation
- [ ] Figures vector or 300 dpi; labels match the text
- [ ] No placeholders, red text or draft marks left
- [ ] Similarity check run on the final file
- [ ] Within the page limit; abstract within the word range
- [ ] City and country for every author
- [ ] Headed Author Contributions section, confirmed by every author
- [ ] Conflict of interest in the venue's wording; funding, data and code statements
- [ ] AI-use statement
- [ ] Every modelled (not measured) parameter listed with its source
- [ ] Price and free-tier figures carry their access date
- [ ] Public repo live, secret-scanned, linked from the paper
- [ ] Built PDF's cover page and body checked before approving

## Sources

Read on 2026-10-15; recheck before relying on any figure.

- [Neon Free plan limits and quotas](https://neon.com/faqs/free-plan-limits-and-quotas)
- [Neon plans](https://neon.com/docs/introduction/plans)
- [Azure SQL Database free offer](https://learn.microsoft.com/en-us/azure/azure-sql/database/free-offer)
- [Aurora Serverless v2 scaling to zero (AWS announcement)](https://aws.amazon.com/about-aws/whats-new/2024/11/amazon-aurora-serverless-v2-scaling-zero-capacity)
- [Aurora Serverless v2 auto-pause documentation](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2-auto-pause.html)
- [Redset dataset (amazon-science on GitHub)](https://github.com/amazon-science/redset)
- [Why TPC Is Not Enough: An Analysis of the Amazon Redshift Fleet (PVLDB 17(11), 2024)](https://vldb.org/pvldb/vol17/p3694-saxena.pdf)
- [PBench: Workload Synthesizer with Real Statistics for Cloud Analytics Benchmarking (arXiv 2506.16379)](https://arxiv.org/pdf/2506.16379)
- [Redbench: Workload Synthesis From Cloud Traces (arXiv 2511.13059)](https://arxiv.org/pdf/2511.13059)
