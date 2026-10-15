"""Download Redset's serverless file (only) to data/redset/, resume-safe.

Resumes from a .part file with an HTTP Range request; renames on completion.
Progress goes to logs/redset_download.log; results/redset_fetch.json on success.
Redset: https://github.com/amazon-science/redset (CC BY-NC 4.0).
"""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import common  # noqa: E402

URL = "https://s3.amazonaws.com/redshift-downloads/redset/serverless/full.parquet"
OUT = common.REPO_ROOT / "data" / "redset" / "serverless_full.parquet"
LOG = common.LOGS_DIR / "redset_download.log"
CHUNK = 1 << 20
RETRIES = 5


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{common.now_ist():%H:%M:%S} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while b := f.read(CHUNK):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    total = int(requests.head(URL, timeout=30).headers["Content-Length"])
    if OUT.exists() and OUT.stat().st_size == total:
        log(f"already complete: {OUT.name} ({total / 1024**2:.1f} MB)")
        return 0
    common.check_free_space(min_gb=common.MIN_FREE_GB + total / 1024**3)
    part = OUT.with_suffix(".parquet.part")
    t0 = time.perf_counter()
    start_bytes = part.stat().st_size if part.exists() else 0
    for attempt in range(1, RETRIES + 1):
        have = part.stat().st_size if part.exists() else 0
        if have >= total:
            break
        log(f"attempt {attempt}: resume at {have / 1024**2:.1f} / {total / 1024**2:.1f} MB")
        try:
            with requests.get(URL, headers={"Range": f"bytes={have}-"}, stream=True,
                              timeout=60) as r:
                r.raise_for_status()
                if have and r.status_code != 206:
                    raise RuntimeError(f"server ignored Range (status {r.status_code})")
                last = time.perf_counter()
                with part.open("ab") as f:
                    for chunk in r.iter_content(CHUNK):
                        f.write(chunk)
                        have += len(chunk)
                        if time.perf_counter() - last > 15:
                            rate = (have - start_bytes) / (time.perf_counter() - t0) / 1024**2
                            eta = (total - have) / 1024**2 / rate if rate else float("nan")
                            log(f"{have / 1024**2:.1f} MB ({100 * have / total:.0f}%), "
                                f"{rate:.2f} MB/s, ETA {eta / 60:.1f} min")
                            last = time.perf_counter()
        except (requests.RequestException, RuntimeError) as e:
            log(f"error: {type(e).__name__}: {e}")
            time.sleep(min(60, 5 * attempt))
    if not part.exists() or part.stat().st_size != total:
        log("FAILED: incomplete after retries; rerun to resume")
        return 1
    part.replace(OUT)
    secs = time.perf_counter() - t0
    digest = sha256(OUT)
    log(f"done: {total / 1024**2:.1f} MB in {secs / 60:.1f} min, sha256 {digest[:16]}…")
    common.write_result("redset_fetch", {
        "file": str(OUT.relative_to(common.REPO_ROOT)), "bytes": total,
        "sha256": digest, "seconds": round(secs, 1),
    }, settings={"url": URL, "licence": "CC BY-NC 4.0"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
