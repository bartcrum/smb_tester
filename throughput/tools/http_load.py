"""HTTP(S) throughput & latency.

A dependency-free concurrent load generator (urllib + threads) for REST and
object-download endpoints, plus parsers for ``wrk`` and ``k6`` output when you
want a heavier external generator. Latency percentiles reuse the latency
probe's ``summarize``.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from ..results import BenchmarkResult, ResultSet
from .latency import summarize

# Drain response bodies in bounded chunks: we only need the byte count, so
# never materialize a whole large download in memory (× concurrency).
_HTTP_CHUNK = 1 << 16


def _one_request(url: str, method: str, data: bytes | None, timeout: float):
    req = urllib.request.Request(url, data=data, method=method)
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        nbytes = 0
        while chunk := resp.read(_HTTP_CHUNK):
            nbytes += len(chunk)
        status = resp.status
    return (time.perf_counter() - t0) * 1000.0, nbytes, status


def run_http_load(url: str, *, requests: int = 100, concurrency: int = 10,
                  method: str = "GET", data: bytes | None = None,
                  timeout: float = 30.0) -> ResultSet:
    """Fire ``requests`` requests at ``concurrency`` and report rps + latency."""
    latencies: list[float] = []
    bytes_total = 0
    statuses: dict[int, int] = {}

    def work(_):
        return _one_request(url, method, data, timeout)

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        for lat_ms, nbytes, status in ex.map(work, range(requests)):
            latencies.append(lat_ms)
            bytes_total += nbytes
            statuses[status] = statuses.get(status, 0) + 1
    elapsed = max(time.perf_counter() - start, 1e-9)

    stats = summarize(latencies)
    meta = {"concurrency": concurrency, "statuses": statuses,
            "p50_ms": stats["p50_ms"], "p95_ms": stats["p95_ms"],
            "avg_ms": stats["avg_ms"]}
    return ResultSet([BenchmarkResult(
        tool="http", target=url, bucket="load",
        operation=method.lower(), bytes_total=bytes_total, ops=requests,
        seconds=elapsed, metadata=meta,
    )])


# -------------------------------------------------------------------- wrk parser
_WRK_REQS = re.compile(r"([\d,]+)\s+requests in\s+([\d.]+)(m?s|m|h),\s+([\d.]+)(\w+)\s+read")
_WRK_RPS = re.compile(r"Requests/sec:\s+([\d.]+)")
_WRK_LAT = re.compile(r"Latency\s+([\d.]+)(\w+)")

_UNIT_S = {"us": 1e-6, "ms": 1e-3, "s": 1.0, "m": 60.0, "h": 3600.0}
_UNIT_B = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3,
           "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}


def parse_wrk(output: str, target: str = "wrk") -> ResultSet:
    reqs_m = _WRK_REQS.search(output)
    if not reqs_m:
        raise ValueError("could not parse wrk summary")
    reqs = int(reqs_m.group(1).replace(",", ""))
    dur = float(reqs_m.group(2)) * _UNIT_S.get(reqs_m.group(3), 1.0)
    read_bytes = float(reqs_m.group(4)) * _UNIT_B.get(reqs_m.group(5), 1)
    lat_m = _WRK_LAT.search(output)
    avg_lat_ms = None
    if lat_m:
        avg_lat_ms = float(lat_m.group(1)) * _UNIT_S.get(lat_m.group(2), 1e-3) * 1000
    return ResultSet([BenchmarkResult(
        tool="http", target=target, bucket="load", operation="get",
        bytes_total=int(read_bytes), ops=reqs, seconds=max(dur, 1e-9),
        metadata={"avg_ms": avg_lat_ms},
    )])


# --------------------------------------------------------------------- k6 parser
def parse_k6_summary(data: dict | str, target: str = "k6") -> ResultSet:
    """Parse k6 ``--summary-export`` JSON."""
    if isinstance(data, str):
        data = json.loads(data)
    metrics = data.get("metrics", data)
    reqs = metrics["http_reqs"]
    count = int(reqs.get("count", 0))
    rate = float(reqs.get("rate", 0)) or 1e-9         # reqs/sec
    seconds = count / rate
    received = float(metrics.get("data_received", {}).get("count", 0))
    dur = metrics.get("http_req_duration", {})
    return ResultSet([BenchmarkResult(
        tool="http", target=target, bucket="load", operation="get",
        bytes_total=int(received), ops=count, seconds=max(seconds, 1e-9),
        metadata={"avg_ms": dur.get("avg"), "p95_ms": dur.get("p(95)")},
    )])
