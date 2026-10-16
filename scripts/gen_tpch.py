"""Generate TPC-H data with DuckDB's tpch extension and export CSV + query texts.

Output: data/tpch_sf<SF>/<table>.csv (header row, comma-delimited) and
sql/queries/qNN.sql for the query subset (DECISIONS E), using the extension's
fixed (validation) substitution parameters.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import common  # noqa: E402

TABLES = ["region", "nation", "supplier", "customer", "part", "partsupp", "orders", "lineitem"]
QUERIES = [1, 3, 4, 5, 6, 10, 12, 14]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sf", type=float, default=0.1)
    args = ap.parse_args()
    sf_tag = f"{args.sf:g}"
    out = common.REPO_ROOT / "data" / f"tpch_sf{sf_tag}"
    out.mkdir(parents=True, exist_ok=True)
    qdir = common.REPO_ROOT / "sql" / "queries"
    qdir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    try:
        con.execute("INSTALL tpch; LOAD tpch;")
    except duckdb.HTTPException:  # Dell G15: http:// repo answers 307; use https directly
        con.execute("INSTALL tpch FROM 'https://extensions.duckdb.org'; LOAD tpch;")
    with common.timed() as t_gen:
        con.execute(f"CALL dbgen(sf={args.sf})")
    rows, sizes = {}, {}
    with common.timed() as t_csv:
        for tbl in TABLES:
            path = out / f"{tbl}.csv"
            con.execute(f"COPY {tbl} TO '{path.as_posix()}' (HEADER, DELIMITER ',')")
            rows[tbl] = con.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
            sizes[tbl] = path.stat().st_size
    for qn, text in con.execute("SELECT query_nr, query FROM tpch_queries()").fetchall():
        if qn in QUERIES:
            (qdir / f"q{qn:02d}.sql").write_text(text.strip() + "\n", encoding="utf-8")

    total_mb = sum(sizes.values()) / 1024**2
    for tbl in TABLES:
        print(f"{tbl:9} {rows[tbl]:>9,} rows  {sizes[tbl] / 1024**2:8.2f} MB")
    print(f"total CSV {total_mb:.1f} MB; dbgen {t_gen['seconds']:.1f}s, export {t_csv['seconds']:.1f}s")
    common.write_result(f"tpch_sf{sf_tag}_gen", {
        "rows": rows, "csv_bytes": sizes, "csv_total_mb": round(total_mb, 2),
        "dbgen_s": round(t_gen["seconds"], 2), "export_s": round(t_csv["seconds"], 2),
        "queries_written": [f"q{q:02d}.sql" for q in QUERIES],
    }, settings={"sf": args.sf, "duckdb": duckdb.__version__, "out_dir": str(out)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
