"""Size-bucket sweep helper, shared by every size-sensitive tool.

The convention (inherited from the SMB tool): hold the *total payload per
bucket constant* so buckets are directly comparable — same bytes moved,
different per-op granularity. The number of ops in a bucket is therefore
``total_payload // size`` (at least 1).
"""

from __future__ import annotations

from typing import Callable

MB = 1024 * 1024

# Default sweep: 4KB .. 256MB, matching the SMB tool's buckets.
_DEFAULT = {
    "4KB": 4 * 1024,
    "16KB": 16 * 1024,
    "64KB": 64 * 1024,
    "256KB": 256 * 1024,
    "1MB": 1 * MB,
    "16MB": 16 * MB,
    "256MB": 256 * MB,
}


def default_byte_sizes() -> dict[str, int]:
    """Return a fresh copy of the default ``label -> bytes`` sweep."""
    return dict(_DEFAULT)


def ops_for_bucket(size_bytes: int, total_payload_bytes: int) -> int:
    """Ops needed to move ``total_payload_bytes`` in ``size_bytes`` chunks."""
    if size_bytes <= 0:
        raise ValueError("size_bytes must be positive")
    return max(1, total_payload_bytes // size_bytes)


def sweep_buckets(
    sizes: dict[str, int],
    total_payload_bytes: int,
    run_bucket: Callable[[str, int, int], object],
):
    """Run ``run_bucket(label, size_bytes, ops)`` for each size, smallest first.

    Yields whatever ``run_bucket`` returns, in ascending size order, so a
    caller can build a :class:`~throughput.results.ResultSet` from real I/O or
    from parsed tool output without re-implementing the ordering/op-count math.
    """
    for label, size in sorted(sizes.items(), key=lambda kv: kv[1]):
        ops = ops_for_bucket(size, total_payload_bytes)
        yield run_bucket(label, size, ops)
