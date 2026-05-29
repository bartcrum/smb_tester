"""Latency / jitter probe.

RTT is the single biggest driver of small-file and small-request rates, so we
capture the *distribution* (min/avg/p50/p95/max), jitter, and loss — not just a
mean. Two front-ends:

* ``tcp_probe`` — pure-Python TCP connect-time RTT (no root, works anywhere).
* ``parse_ping`` — parse ``ping`` output when ICMP RTT is wanted.

Both feed ``summarize``; the stats live in result metadata (bucket="rtt").
"""

from __future__ import annotations

import re
import socket
import statistics
import time
from typing import Callable

from ..results import BenchmarkResult, ResultSet


def summarize(samples_ms: list[float], sent: int | None = None) -> dict:
    """Distribution + jitter + loss from per-probe RTTs (None = lost)."""
    ok = [s for s in samples_ms if s is not None]
    sent = sent if sent is not None else len(samples_ms)
    received = len(ok)
    loss_pct = round((sent - received) / sent * 100, 3) if sent else 0.0
    if not ok:
        return {"sent": sent, "received": 0, "loss_pct": loss_pct,
                "min_ms": None, "avg_ms": None, "max_ms": None,
                "p50_ms": None, "p95_ms": None, "jitter_ms": None}
    ordered = sorted(ok)

    def pct(p: float) -> float:
        idx = min(len(ordered) - 1, int(round((p / 100) * (len(ordered) - 1))))
        return round(ordered[idx], 3)

    # Jitter: mean absolute difference of consecutive samples (RFC3550-style).
    jitter = (round(statistics.fmean(abs(b - a) for a, b in zip(ok, ok[1:])), 3)
              if len(ok) > 1 else 0.0)
    return {
        "sent": sent, "received": received, "loss_pct": loss_pct,
        "min_ms": round(min(ok), 3), "avg_ms": round(statistics.fmean(ok), 3),
        "max_ms": round(max(ok), 3), "p50_ms": pct(50), "p95_ms": pct(95),
        "jitter_ms": jitter,
    }


def _to_result(target: str, operation: str, samples_ms: list[float],
               elapsed: float) -> BenchmarkResult:
    stats = summarize(samples_ms)
    return BenchmarkResult(
        tool="latency", target=target, bucket="rtt", operation=operation,
        bytes_total=0, ops=stats["received"] or 1, seconds=elapsed or 1e-9,
        metadata=stats,
    )


def probe(target: str, connect_fn: Callable[[], float | None], count: int,
          operation: str = "connect", interval: float = 0.0) -> ResultSet:
    """Run ``connect_fn`` ``count`` times; it returns RTT ms or None (loss)."""
    samples: list[float] = []
    start = time.perf_counter()
    for i in range(count):
        samples.append(connect_fn())
        if interval and i < count - 1:
            time.sleep(interval)
    elapsed = time.perf_counter() - start
    return ResultSet([_to_result(target, operation, samples, elapsed)])


def tcp_probe(host: str, port: int = 445, count: int = 10,
              timeout: float = 2.0, interval: float = 0.0) -> ResultSet:
    """Measure TCP connect RTT to ``host:port`` (default 445 = SMB)."""
    def connect_once() -> float | None:
        t0 = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return (time.perf_counter() - t0) * 1000.0
        except OSError:
            return None
    return probe(f"{host}:{port}", connect_once, count,
                 operation="connect", interval=interval)


_RTT_RE = re.compile(
    r"=\s*([\d.]+)/([\d.]+)/([\d.]+)(?:/([\d.]+))?\s*ms")
_LOSS_RE = re.compile(r"([\d.]+)%\s*packet loss")


def parse_ping(output: str, target: str = "unknown") -> ResultSet:
    """Parse Linux/BSD ``ping`` output into a latency result."""
    loss_m = _LOSS_RE.search(output)
    rtt_m = _RTT_RE.search(output)
    stats = {"min_ms": None, "avg_ms": None, "max_ms": None,
             "jitter_ms": None, "loss_pct": None}
    if loss_m:
        stats["loss_pct"] = float(loss_m.group(1))
    if rtt_m:
        stats["min_ms"] = float(rtt_m.group(1))
        stats["avg_ms"] = float(rtt_m.group(2))
        stats["max_ms"] = float(rtt_m.group(3))
        if rtt_m.group(4):  # mdev/stddev field on Linux
            stats["jitter_ms"] = float(rtt_m.group(4))
    return ResultSet([BenchmarkResult(
        tool="latency", target=target, bucket="rtt", operation="icmp",
        bytes_total=0, ops=1, seconds=1e-9, metadata=stats,
    )])
