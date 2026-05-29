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


# -------------------------------------------------------------------- hey parser
_HEY_TOTAL = re.compile(r"Total:\s+([\d.]+)\s+secs")
_HEY_RPS = re.compile(r"Requests/sec:\s+([\d.]+)")
_HEY_DATA = re.compile(r"Total data:\s+(\d+)\s+bytes")
_HEY_AVG = re.compile(r"Average:\s+([\d.]+)\s+secs")
_HEY_P95 = re.compile(r"95%\s+in\s+([\d.]+)\s+secs")
_HEY_STATUS = re.compile(r"\[(\d+)\]\s+(\d+)\s+responses")


def parse_hey(output: str, target: str = "hey") -> ResultSet:
    """Parse ``hey`` summary text (rakyll/hey, GET-oriented load tool)."""
    total_m = _HEY_TOTAL.search(output)
    rps_m = _HEY_RPS.search(output)
    if not total_m or not rps_m:
        raise ValueError("could not parse hey summary")
    seconds = float(total_m.group(1))
    rps = float(rps_m.group(1))
    statuses = {int(c): int(n) for c, n in _HEY_STATUS.findall(output)}
    ops = sum(statuses.values()) or round(rps * seconds)
    data_m = _HEY_DATA.search(output)
    bytes_total = int(data_m.group(1)) if data_m else 0
    avg_m = _HEY_AVG.search(output)
    p95_m = _HEY_P95.search(output)
    meta = {"rps": rps, "statuses": statuses,
            "avg_ms": float(avg_m.group(1)) * 1000 if avg_m else None,
            "p95_ms": float(p95_m.group(1)) * 1000 if p95_m else None}
    return ResultSet([BenchmarkResult(
        tool="http", target=target, bucket="load", operation="get",
        bytes_total=bytes_total, ops=max(ops, 1), seconds=max(seconds, 1e-9),
        metadata=meta,
    )])


# ----------------------------------------------------------------- vegeta parser
_NS_PER_MS = 1e6


def parse_vegeta(data: dict | str, target: str = "vegeta") -> ResultSet:
    """Parse ``vegeta report -type=json`` output.

    vegeta reports latencies and durations in nanoseconds; we normalize latency
    to milliseconds (suite convention) and duration to seconds.
    """
    if isinstance(data, str):
        data = json.loads(data)
    requests = int(data.get("requests", 0))
    duration_ns = float(data.get("duration", 0)) or (
        requests / (float(data.get("rate", 0)) or 1e-9) * 1e9)
    seconds = duration_ns / 1e9
    bytes_total = int(data.get("bytes_in", {}).get("total", 0))
    lat = data.get("latencies", {})
    meta = {
        "rate": data.get("rate"),
        "throughput": data.get("throughput"),
        "success": data.get("success"),
        "status_codes": data.get("status_codes", {}),
        "avg_ms": lat.get("mean", 0) / _NS_PER_MS if "mean" in lat else None,
        "p50_ms": lat.get("50th", 0) / _NS_PER_MS if "50th" in lat else None,
        "p95_ms": lat.get("95th", 0) / _NS_PER_MS if "95th" in lat else None,
        "max_ms": lat.get("max", 0) / _NS_PER_MS if "max" in lat else None,
    }
    return ResultSet([BenchmarkResult(
        tool="http", target=target, bucket="load", operation="get",
        bytes_total=bytes_total, ops=max(requests, 1), seconds=max(seconds, 1e-9),
        metadata=meta,
    )])
