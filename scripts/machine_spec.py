"""Record the measurement host's hardware -> results/machine_dell.json."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import common  # noqa: E402


def ps_json(cmd: str):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", f"{cmd} | ConvertTo-Json -Depth 3"],
                       capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout)


def main() -> int:
    cpu = ps_json("Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,"
                  "NumberOfLogicalProcessors,MaxClockSpeed")
    cs = ps_json("Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,TotalPhysicalMemory")
    gpu = ps_json("Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion")
    os_ = ps_json("Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber")
    disks = ps_json("Get-PSDrive -PSProvider FileSystem | Where-Object Used -ne $null | "
                    "Select-Object Name,@{n='free_gb';e={[math]::Round($_.Free/1GB,1)}},"
                    "@{n='used_gb';e={[math]::Round($_.Used/1GB,1)}}")
    data = {
        "machine": f"{cs['Manufacturer']} {cs['Model']}",
        "cpu": cpu["Name"].strip(), "cores": cpu["NumberOfCores"],
        "threads": cpu["NumberOfLogicalProcessors"], "max_clock_mhz": cpu["MaxClockSpeed"],
        "ram_gb": round(cs["TotalPhysicalMemory"] / 1024**3, 2),
        "gpu": [g["Name"] for g in (gpu if isinstance(gpu, list) else [gpu])],
        "windows": os_["Caption"], "windows_version": os_["Version"], "windows_build": os_["BuildNumber"],
        "drives": disks,
        "note": "i5-13450HX is hybrid: 6 P-cores (12 threads) + 4 E-cores (4 threads)",
    }
    print(json.dumps(data, indent=2))
    common.write_result("machine_dell", data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
