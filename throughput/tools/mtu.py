"""Path-MTU discovery.

Fragmentation silently caps throughput; a path that can't carry the MTU you
think it can will quietly halve large-transfer performance. This binary-searches
the largest unfragmented payload along the path.

``discover_payload`` is pure (inject any probe predicate); ``path_mtu`` drives
it with ``ping -M do`` (Linux) / ``ping -D`` (BSD).
"""

from __future__ import annotations

from typing import Callable

from ..results import BenchmarkResult, ResultSet
from ._proc import require, run_capture

# ICMP echo (8) + IPv4 header (20). MTU = passing payload + this.
ICMP_IP_OVERHEAD = 28


def discover_payload(probe_fn: Callable[[int], bool],
                     low: int = 0, high: int = 9000) -> int:
    """Largest payload size for which ``probe_fn(size)`` is True (binary search).

    Assumes monotonic: if size N passes, every size < N passes. Returns ``low``
    if even that doesn't pass.
    """
    if not probe_fn(low):
        return low
    best = low
    lo, hi = low, high
    while lo <= hi:
        mid = (lo + hi) // 2
        if probe_fn(mid):
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def to_mtu(payload: int, overhead: int = ICMP_IP_OVERHEAD) -> int:
    return payload + overhead


def _result(target: str, payload: int) -> ResultSet:
    mtu = to_mtu(payload)
    return ResultSet([BenchmarkResult(
        tool="mtu", target=target, bucket="mtu", operation="discover",
        bytes_total=0, ops=1, seconds=1e-9,
        metadata={"max_payload": payload, "path_mtu": mtu,
                  "jumbo": mtu > 1500, "standard_1500": mtu == 1500},
    )])


def build_ping_command(host: str, payload_size: int, *,
                       linux: bool = True, count: int = 1,
                       timeout_s: int = 2) -> list[str]:
    """ping command that forbids fragmentation for a given payload size."""
    if linux:
        return ["ping", "-c", str(count), "-W", str(timeout_s),
                "-M", "do", "-s", str(payload_size), host]
    # BSD/macOS
    return ["ping", "-c", str(count), "-D", "-s", str(payload_size), host]


def path_mtu(host: str, *, low: int = 0, high: int = 9000,
             linux: bool = True) -> ResultSet:
    require("ping")

    def probe(size: int) -> bool:
        try:
            run_capture(build_ping_command(host, size, linux=linux), timeout=10)
            return True
        except RuntimeError:
            return False  # non-zero exit => fragmentation needed / unreachable

    payload = discover_payload(probe, low=low, high=high)
    return _result(f"{host}", payload)
