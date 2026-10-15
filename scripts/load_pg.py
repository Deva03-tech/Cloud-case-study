"""Load TPC-H CSVs into PostgreSQL: schema, COPY, keys, ANALYZE, size report.

  python scripts/load_pg.py --target docker   # DSN from configs/docker.yaml
  python scripts/load_pg.py --target neon     # DSN from .env NEON_DSN

Fails (exit 1) if the Neon database exceeds 0.4 GB (DECISIONS E).
Writes results/load_<target>_sf<SF>.json.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import common  # noqa: E402

TABLES = ["region", "nation", "supplier", "customer", "part", "partsupp", "orders", "lineitem"]
NEON_MAX_GB = 0.4


def docker_dsn() -> str:
    cfg = yaml.safe_load((common.REPO_ROOT / "configs" / "docker.yaml").read_text())
    return (f"host={cfg['host']} port={cfg['port']} user={cfg['user']} "
            f"password={cfg['password']} dbname={cfg['database']}")


def dsn_for(target: str) -> str:
    if target == "docker":
        return docker_dsn()
    common.load_env(required=("NEON_DSN",))
    return os.environ["NEON_DSN"]


def run_sql_file(conn, path: Path) -> None:
    conn.execute(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["docker", "neon"], required=True)
    ap.add_argument("--sf", type=float, default=0.1)
    args = ap.parse_args()
    sf_tag = f"{args.sf:g}"
    csv_dir = common.REPO_ROOT / "data" / f"tpch_sf{sf_tag}"
    missing = [t for t in TABLES if not (csv_dir / f"{t}.csv").exists()]
    if missing:
        print(f"missing CSVs in {csv_dir}: {missing}; run scripts/gen_tpch.py first")
        return 1

    timings = {}
    with psycopg.connect(dsn_for(args.target), autocommit=True, connect_timeout=60) as conn:
        with common.timed() as t:
            run_sql_file(conn, common.REPO_ROOT / "sql" / "schema.sql")
        timings["schema_s"] = t["seconds"]
        with common.timed() as t:
            for tbl in TABLES:
                path = csv_dir / f"{tbl}.csv"
                with path.open("rb") as f, conn.cursor() as cur:
                    with cur.copy(f"COPY {tbl} FROM STDIN (FORMAT csv, HEADER true)") as cp:
                        while chunk := f.read(1 << 20):
                            cp.write(chunk)
                print(f"copied {tbl}")
        timings["copy_s"] = t["seconds"]
        with common.timed() as t:
            run_sql_file(conn, common.REPO_ROOT / "sql" / "keys.sql")
        timings["keys_s"] = t["seconds"]
        with common.timed() as t:
            conn.execute("ANALYZE")
        timings["analyze_s"] = t["seconds"]
        db_bytes = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
        rows = {tbl: conn.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0] for tbl in TABLES}
        server = conn.execute("SHOW server_version").fetchone()[0]

    db_gb = db_bytes / 1024**3
    ok = not (args.target == "neon" and db_gb > NEON_MAX_GB)
    print(f"{args.target}: database size {db_bytes / 1024**2:.1f} MB; "
          + ", ".join(f"{k} {v:.1f}s" for k, v in timings.items()))
    common.write_result(f"load_{args.target}_sf{sf_tag}", {
        "db_bytes": db_bytes, "db_mb": round(db_bytes / 1024**2, 1), "rows": rows,
        "server_version": server, "within_limit": ok,
        **{k: round(v, 2) for k, v in timings.items()},
    }, settings={"target": args.target, "sf": args.sf, "neon_max_gb": NEON_MAX_GB})
    if not ok:
        print(f"FAIL: Neon database {db_gb:.3f} GB > {NEON_MAX_GB} GB; use SF 0.05")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
