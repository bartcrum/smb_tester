"""Parallel filesystem read/write sweep — the Python analog of the SMB tool.

Runs against any mounted path, so it serves several roadmap items with one
engine: an NFS sweep (``tool="nfs"`` against an NFS mount), an SMB-mount sweep,
or a local-disk baseline (``tool="disk"`` against a local dir, ideally RAM- or
SSD-backed to isolate storage from the wire).

Same convention as the SMB tool: constant total payload per bucket, report MB/s
*and* files/s. This actually moves bytes, so it runs and is tested here.
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..buckets import default_byte_sizes, ops_for_bucket
from ..results import BenchmarkResult, ResultSet, MB


def _write_file(path: Path, buf: bytes, fsync: bool) -> None:
    with open(path, "wb") as fh:
        fh.write(buf)
        if fsync:
            fh.flush()
            os.fsync(fh.fileno())


def _read_file(path: Path) -> int:
    with open(path, "rb") as fh:
        return len(fh.read())


def _timed(fn, items, threads: int) -> float:
    start = time.perf_counter()
    if threads <= 1:
        for it in items:
            fn(it)
    else:
        with ThreadPoolExecutor(max_workers=threads) as ex:
            list(ex.map(fn, items))
    return max(time.perf_counter() - start, 1e-9)


def run_sweep(path: str | Path, *, sizes: dict[str, int] | None = None,
              total_payload_bytes: int = 256 * MB, threads: int = 8,
              do_read: bool = True, tool: str = "file",
              fsync: bool = False) -> ResultSet:
    """Sweep read/write throughput across size buckets at ``path``."""
    sizes = sizes or default_byte_sizes()
    base = Path(path)
    test_dir = base / f"sweep_{uuid.uuid4().hex[:8]}"
    test_dir.mkdir(parents=True, exist_ok=True)
    rs = ResultSet()
    try:
        for label, size in sorted(sizes.items(), key=lambda kv: kv[1]):
            ops = ops_for_bucket(size, total_payload_bytes)
            buf = os.urandom(size)
            files = [test_dir / f"f_{i}.dat" for i in range(ops)]

            w_secs = _timed(lambda f: _write_file(f, buf, fsync), files, threads)
            rs.add(BenchmarkResult(
                tool=tool, target=str(base), bucket=label, operation="write",
                bytes_total=size * ops, ops=ops, seconds=w_secs, size_bytes=size,
                metadata={"threads": threads, "fsync": fsync},
            ))

            if do_read:
                r_secs = _timed(_read_file, files, threads)
                rs.add(BenchmarkResult(
                    tool=tool, target=str(base), bucket=label, operation="read",
                    bytes_total=size * ops, ops=ops, seconds=r_secs,
                    size_bytes=size, metadata={"threads": threads},
                ))

            for f in files:
                f.unlink(missing_ok=True)
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)
    return rs


def run_nfs(mount_path, **kw) -> ResultSet:
    """Convenience: filesystem sweep labeled as NFS (point at an NFS mount)."""
    kw.setdefault("tool", "nfs")
    return run_sweep(mount_path, **kw)
