"""iperf3 wrapper — raw TCP/UDP line-rate baseline.

This is the ceiling the protocol-level tools (SMB, NFS, S3, HTTP) are measured
against. If iperf3 hits NIC line rate but SMB crawls, the bottleneck is the
protocol/latency, not bandwidth.

``build_command`` and ``parse`` are pure; ``run`` shells out to iperf3 -J.
"""

from __future__ import annotations

import json
from typing import Any

from ..results import BenchmarkResult, ResultSet
from ._proc import require, run_capture


def build_command(
    host: str,
    *,
    port: int = 5201,
    duration: int = 10,
    parallel: int = 1,
    reverse: bool = False,
    udp: bool = False,
    bitrate: str | None = None,
) -> list[str]:
    cmd = ["iperf3", "-c", host, "-p", str(port), "-t", str(duration),
           "-P", str(parallel), "-J"]
    if reverse:
        cmd.append("-R")
    if udp:
        cmd.append("-u")
    if bitrate:
        cmd += ["-b", bitrate]
    return cmd


def _result(target: str, operation: str, sum_obj: dict[str, Any],
            extra: dict[str, Any]) -> BenchmarkResult:
    meta = {"bits_per_second": sum_obj.get("bits_per_second"), **extra}
    return BenchmarkResult(
        tool="iperf3",
        target=target,
        bucket=extra.get("protocol", "tcp"),
        operation=operation,
        bytes_total=int(sum_obj.get("bytes", 0)),
        ops=int(sum_obj.get("packets", 0)) or 1,
        seconds=float(sum_obj.get("seconds", 0.0)) or 1e-9,
        metadata={k: v for k, v in meta.items() if v is not None},
    )


def parse(data: dict[str, Any] | str, target: str | None = None) -> ResultSet:
    """Parse iperf3 JSON (``-J``) into send/recv results."""
    if isinstance(data, str):
        data = json.loads(data)

    end = data["end"]
    test = data.get("start", {}).get("test_start", {})
    protocol = (test.get("protocol") or "TCP").lower()
    host = target or data.get("start", {}).get("connecting_to", {}).get("host") or "unknown"

    rs = ResultSet()
    if protocol == "udp":
        # UDP reports a single 'sum' plus jitter/loss.
        s = end.get("sum", {})
        rs.add(_result(host, "send", s, {
            "protocol": "udp",
            "jitter_ms": s.get("jitter_ms"),
            "lost_packets": s.get("lost_packets"),
            "lost_percent": s.get("lost_percent"),
        }))
    else:
        if "sum_sent" in end:
            rs.add(_result(host, "send", end["sum_sent"],
                           {"protocol": "tcp",
                            "retransmits": end["sum_sent"].get("retransmits")}))
        if "sum_received" in end:
            rs.add(_result(host, "recv", end["sum_received"],
                           {"protocol": "tcp"}))
    return rs


def run(host: str, **kw) -> ResultSet:
    require("iperf3")
    out = run_capture(build_command(host, **kw),
                      timeout=kw.get("duration", 10) + 15)
    return parse(out, target=host)
