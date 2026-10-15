# Serverless vs Provisioned Cloud Relational Databases Under Burst Analytics Workloads

Code, data generators, calibration measurements and simulator for the paper
"A Simulation-Based Comparative Analysis of Serverless and Provisioned Cloud
Relational Databases Under Burst Analytics Workloads".

Status: work in progress. See `STATUS.md` for progress, `DECISIONS.md` for every
design choice and `HANDOVER.md` for the project brief.

## Layout

| Path | Contents |
| --- | --- |
| `src/` | Shared library code (simulator, cost model, helpers) |
| `scripts/` | Runnable entry points (data generation, loading, calibration, sweeps) |
| `configs/` | YAML configuration (Docker sizes, grids, prices) |
| `sql/` | TPC-H schema, keys, indexes and queries |
| `data/` | Generated TPC-H CSV and Redset slice (git-ignored) |
| `results/` | Result JSON files, one per task |
| `figures/` | Vector PDF figures generated from `results/` |
| `paper/` | LaTeX source |
| `tests/` | pytest suite |

## Setup

Requires Python 3.12 and Docker Desktop (WSL2).

```
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env   # then fill in the Neon values
```
