## Open threats to validity

- **No real serverless measurement.** No Neon `.env` arrived, so serverless behaviour (15 s resume, scale-up doubling every 5 s, scale-down halving after 60 s, 0.25 vCPU-eq minimum) is modelled from AWS documentation and assumptions, not measured. The scaling constants are not documented by AWS. Neon RTT was not measured, so RTT = 0 everywhere.
- **Validation is simulator vs real Docker provisioned (s2), not vs a real serverless replay.** It checks the queueing and service-time model only; it cannot test resume, scaling or billing. Billed compute-seconds match by construction, so compute-seconds were validated as consumed CPU-seconds. The replay was 10 min (planned 45 min on Neon).
- **CPU quotas, not pinned cores.** Docker sizes use `--cpus` quotas on a hybrid i5-13450HX (6 P + 4 E cores); WSL2 vCPUs do not map to fixed core types.
- **Free-plan 5-min fixed suspend.** Neon Free suspends after a fixed 5 min. Timeouts other than 300 s (S-tuned candidates 60/120/600/1800 s) correspond to paid plans (Neon Scale: 1 min to always on; Aurora: 300 s minimum, so 60/120 s are not available on Aurora).
- **Single machine, single run of calibration.** One laptop and one calibration pass (3 cold + 5 warm per query and size); no confirmatory repeat.
- **Capacity equivalence** (1 vCPU = 1 Neon CU = 2 Aurora ACU) and linear per-vCPU RDS pricing are modelling choices. The RDS price comes from a third-party mirror of the AWS price list.
- **S-tuned is selected in-sample** on the same 10 seeds it is evaluated on (optimistic). **P-sched resizes instantly** on a known schedule; real RDS resizes take minutes. Redset arrivals are mapped to TPC-H queries at random, and P-sched on Redset uses an oracle hourly schedule.
- **Small scale factor** (TPC-H SF 0.1, 8 queries) and short simulated horizons (3 h for the synthetic sweep, 24 h for Redset).
