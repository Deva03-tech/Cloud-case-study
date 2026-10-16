"""Environment check: versions, CPU, power, Docker/WSL resources, disk, Neon.

Prints a pass/fail table and writes results/env_check.json. Exit code 1 if any
check fails. Never prints secrets.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import common  # noqa: E402

PACKAGES = ["psycopg", "duckdb", "pandas", "pyarrow", "numpy", "scipy", "simpy",
            "matplotlib", "requests", "python-dotenv", "PyYAML", "pytest", "detect-secrets"]
WSL_MEMORY = "9GB"  # Dell G15: 15.7 GB total minus 6 GB, rounded down
OVERLAYS = {
    "961cc777-2547-4f9d-8174-7d86181b8a7a": "Best power efficiency",
    "00000000-0000-0000-0000-000000000000": "Balanced",
    "3af9b8d9-7c97-431d-ad78-34a8bfea439f": "Better performance",
    "ded574b5-45a0-4f42-8737-46345c09c238": "Best performance",
}


def ps(cmd: str, timeout: int = 30) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()


def check_python():
    v = sys.version.split()[0]
    # Dell G15: only 3.11/3.13 installed; 3.13 has wheels for every pin (DECISIONS).
    return v.startswith(("3.12", "3.13")), v, {"python": v, "executable": sys.executable}


def check_packages():
    vers, missing = {}, []
    for p in PACKAGES:
        try:
            vers[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            missing.append(p)
    detail = "all present" if not missing else f"missing: {', '.join(missing)}"
    return not missing, detail, vers


def check_cpu():
    out = ps("Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,"
             "NumberOfLogicalProcessors | ConvertTo-Json")
    d = json.loads(out)
    return True, f"{d['Name'].strip()} ({d['NumberOfCores']}C/{d['NumberOfLogicalProcessors']}T)", d


def check_power_plan():
    scheme = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True,
                            text=True).stdout.strip()
    ov = json.loads(ps(
        "Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Power\\User\\PowerSchemes' |"
        " Select-Object ActiveOverlayAcPowerScheme,ActiveOverlayDcPowerScheme | ConvertTo-Json"))
    ac = OVERLAYS.get(ov.get("ActiveOverlayAcPowerScheme") or "", ov.get("ActiveOverlayAcPowerScheme"))
    dc = OVERLAYS.get(ov.get("ActiveOverlayDcPowerScheme") or "", ov.get("ActiveOverlayDcPowerScheme"))
    ok = "High performance" in scheme or ac == "Best performance"
    return ok, f"{scheme.split('(')[-1].rstrip(')')}; power mode AC={ac}, DC={dc}", {
        "scheme": scheme, "overlay_ac": ac, "overlay_dc": dc}


def check_ac_power():
    out = ps("(Get-CimInstance Win32_Battery | Select-Object BatteryStatus,"
             "EstimatedChargeRemaining | ConvertTo-Json)")
    if not out:
        return True, "no battery reported (assume AC)", {}
    d = json.loads(out)
    on_ac = d.get("BatteryStatus") in (2, 6, 7, 8, 9)  # AC / charging states
    return on_ac, f"{'yes' if on_ac else 'NO (on battery)'}, charge {d.get('EstimatedChargeRemaining')}%", d


def check_wslconfig():
    p = Path(os.environ["USERPROFILE"]) / ".wslconfig"
    if not p.exists():
        return False, "missing", {}
    vals = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    want = {"memory": WSL_MEMORY, "processors": str(os.cpu_count()), "swap": "4GB"}
    ok = all(vals.get(k) == v for k, v in want.items())
    return ok, ", ".join(f"{k}={vals.get(k)}" for k in want), vals


def check_docker():
    try:
        r = subprocess.run(["docker", "info", "--format",
                            "{{json .ServerVersion}} {{.NCPU}} {{.MemTotal}}"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"docker not callable: {e}", {}
    if r.returncode != 0 or not r.stdout.strip().startswith('"'):
        return False, "engine not reachable", {"stderr": r.stderr.strip()[-300:]}
    ver, ncpu, mem = r.stdout.split()
    ver = json.loads(ver)
    mem_gb = int(mem) / 1024**3
    ncpu = int(ncpu)
    # WSL reports slightly under the .wslconfig memory cap.
    cap = float(WSL_MEMORY.rstrip("GB"))
    ok = ncpu == os.cpu_count() and cap - 1.5 <= mem_gb <= cap + 0.5
    return ok, f"server {ver}; WSL2 sees {ncpu} CPUs, {mem_gb:.1f} GB", {
        "server_version": ver, "ncpu": ncpu, "mem_gb": round(mem_gb, 2)}


def check_disk():
    c, d = common.free_gb("C:\\"), common.free_gb(common.DATA_DRIVE)
    ok = c >= common.MIN_FREE_GB_C and d >= common.MIN_FREE_GB
    return ok, (f"C: {c:.1f} GB free (stop {common.MIN_FREE_GB_C:.0f}), "
                f"D: {d:.1f} GB free (stop {common.MIN_FREE_GB:.0f})"), {
        "c_free_gb": round(c, 1), "d_free_gb": round(d, 1)}


def check_neon():
    try:
        common.load_env(required=("NEON_DSN",))
    except RuntimeError as e:
        return False, f"no .env / {e}", {}
    import psycopg
    try:
        with common.timed() as t, psycopg.connect(os.environ["NEON_DSN"], connect_timeout=30) as conn:
            server = conn.execute("show server_version").fetchone()[0]
            conn.execute("select 1").fetchone()
    except Exception as e:  # report the class only; messages can echo host names
        return False, f"connect failed: {type(e).__name__}", {"error": type(e).__name__}
    return True, f"reachable, PostgreSQL {server}, connect+query {t['seconds']:.2f}s", {
        "server_version": server, "connect_and_select1_s": round(t["seconds"], 3)}


CHECKS = [
    ("Python 3.12/3.13", check_python),
    ("Packages", check_packages),
    ("CPU", check_cpu),
    ("Power plan / mode", check_power_plan),
    ("AC power", check_ac_power),
    (".wslconfig", check_wslconfig),
    ("Docker / WSL2", check_docker),
    ("Disk", check_disk),
    ("Neon", check_neon),
]


def main() -> int:
    rows, data = [], {}
    for name, fn in CHECKS:
        try:
            ok, detail, extra = fn()
        except Exception as e:
            ok, detail, extra = False, f"check error: {type(e).__name__}: {e}", {}
        rows.append((name, ok, detail))
        data[name] = {"pass": ok, "detail": detail, **extra}
    w = max(len(n) for n, _, _ in rows)
    print(f"{'Check'.ljust(w)}  Result  Detail")
    for n, ok, d in rows:
        print(f"{n.ljust(w)}  {'PASS' if ok else 'FAIL':6}  {d}")
    n_fail = sum(not ok for _, ok, _ in rows)
    print(f"\n{len(rows) - n_fail}/{len(rows)} passed")
    path = common.write_result("env_check", data, settings={"checks": [n for n, _ in CHECKS]})
    print(f"wrote {path.relative_to(common.REPO_ROOT)}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
