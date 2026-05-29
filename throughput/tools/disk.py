"""Local disk baseline via fio (Linux/macOS) or diskspd (Windows).

Benchmarking the target's *local* disk isolates storage from the wire, so a
slow SMB/NFS run can be attributed to spindle/SSD vs network. Command building
and output parsing are pure; ``run_fio`` shells out to ``fio --output-format=json``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..results import BenchmarkResult, ResultSet


# --------------------------------------------------------------------------- fio
def build_fio_command(filename: str, *, rw: str = "readwrite", bs: str = "1m",
                      size: str = "1G", numjobs: int = 1, iodepth: int = 16,
                      direct: bool = True, runtime: int | None = None,
                      name: str = "bench") -> list[str]:
    cmd = ["fio", f"--name={name}", f"--filename={filename}", f"--rw={rw}",
           f"--bs={bs}", f"--size={size}", f"--numjobs={numjobs}",
           f"--iodepth={iodepth}", f"--direct={1 if direct else 0}",
           "--output-format=json"]
    if runtime is not None:
        cmd += [f"--runtime={runtime}", "--time_based"]
    return cmd


def _fio_section(target: str, bucket: str, op: str, sec: dict[str, Any]) -> BenchmarkResult:
    bw_bytes = float(sec.get("bw_bytes", 0))          # bytes/sec
    runtime_s = max(float(sec.get("runtime", 0)) / 1000.0, 1e-9)  # ms -> s
    iops = float(sec.get("iops", 0))
    return BenchmarkResult(
        tool="disk", target=target, bucket=bucket, operation=op,
        bytes_total=int(bw_bytes * runtime_s), ops=max(int(iops * runtime_s), 1),
        seconds=runtime_s,
        metadata={"iops": round(iops, 1),
                  "lat_ns_mean": sec.get("lat_ns", {}).get("mean")},
    )


def parse_fio(data: dict[str, Any] | str, target: str | None = None) -> ResultSet:
    if isinstance(data, str):
        data = json.loads(data)
    rs = ResultSet()
    for job in data.get("jobs", []):
        name = job.get("jobname", "job")
        opts = job.get("job options", {})
        bucket = opts.get("bs", name)
        tgt = target or opts.get("filename", "local")
        for op in ("read", "write"):
            sec = job.get(op, {})
            if sec and float(sec.get("bw_bytes", 0)) > 0:
                rs.add(_fio_section(tgt, bucket, op, sec))
    return rs


def run_fio(filename: str, **kw) -> ResultSet:
    from ._proc import require, run_capture
    require("fio")
    out = run_capture(build_fio_command(filename, **kw),
                      timeout=(kw.get("runtime") or 60) + 30)
    return parse_fio(out, target=filename)


# ----------------------------------------------------------------------- diskspd
# diskspd prints "Read IO" / "Write IO" sections, each ending with a
# "total:  <bytes> | <ios> | <MiB/s> | <IOPS> | ..." line.
_DISKSPD_TOTAL = re.compile(
    r"total:\s*([\d.]+)\s*\|\s*(\d+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)")


def parse_diskspd(text: str, target: str = "local") -> ResultSet:
    rs = ResultSet()
    section = None
    for line in text.splitlines():
        low = line.strip().lower()
        if low.startswith("read io"):
            section = "read"
        elif low.startswith("write io"):
            section = "write"
        elif low.startswith("total io"):
            section = None  # combined section; skip, we want per-op
        m = _DISKSPD_TOTAL.search(line)
        if m and section:
            total_bytes, ios, mibps, iops = m.groups()
            mbps = float(mibps)  # MiB/s
            seconds = (int(total_bytes) / (1024 * 1024)) / max(mbps, 1e-9)
            rs.add(BenchmarkResult(
                tool="disk", target=target, bucket="diskspd",
                operation=section, bytes_total=int(total_bytes), ops=int(ios),
                seconds=max(seconds, 1e-9), metadata={"iops": float(iops)},
            ))
    return rs
