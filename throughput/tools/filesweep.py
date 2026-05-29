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
from pathlib import Path

from ..buckets import default_byte_sizes, ops_for_bucket
from ..results import BenchmarkResult, ResultSet, MB
from ._parallel import map_chunked
from ._payload import random_payload

# Read in bounded chunks so we never hold a whole large file in memory just to
# count its bytes (a 256 MB file × N threads would otherwise spike RSS).
_READ_CHUNK = 1 << 20

# Cap files per directory so the smallest bucket (tens of thousands of tiny
# files) doesn't pile into one directory and hit filesystem dir-scaling costs.
_FILES_PER_DIR = 1000


def _write_file(path: Path, buf, fsync: bool) -> None:
    with open(path, "wb") as fh:
        fh.write(buf)
        if fsync:
            fh.flush()
            os.fsync(fh.fileno())


def _read_file(path: Path) -> int:
    total = 0
    with open(path, "rb") as fh:
        while chunk := fh.read(_READ_CHUNK):
            total += len(chunk)
    return total


def _bucket_paths(test_dir: Path, ops: int) -> list[Path]:
    """Pre-create sharded subdirs and return ``ops`` file paths spread across them."""
    ndirs = max(1, (ops + _FILES_PER_DIR - 1) // _FILES_PER_DIR)
    dirs = []
    for d in range(ndirs):
        sub = test_dir / f"d{d:04d}"
        sub.mkdir(exist_ok=True)
        dirs.append(sub)
    return [dirs[i // _FILES_PER_DIR] / f"f_{i}.dat" for i in range(ops)]


def _timed(fn, items, threads: int) -> float:
    start = time.perf_counter()
    map_chunked(fn, items, threads)
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
            buf = random_payload(size)
            files = _bucket_paths(test_dir, ops)

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


def run_nfs(mount_path, *, with_context: bool = False, **kw) -> ResultSet:
    """Convenience: filesystem sweep labeled as NFS (point at an NFS mount).

    With ``with_context=True`` the negotiated NFS mount options and client RPC
    retransmit rate (via ``nfsstat``) are attached to each result's metadata
    under ``"nfs_context"`` — the NFS analog of the SMB tool's connection
    diagnostics. Degrades silently if ``nfsstat`` is unavailable.
    """
    kw.setdefault("tool", "nfs")
    rs = run_sweep(mount_path, **kw)
    if with_context:
        from .nfsstat import collect_context
        try:
            ctx = collect_context(str(mount_path))
        except Exception:
            ctx = None
        if ctx:
            for r in rs:
                r.metadata["nfs_context"] = ctx
    return rs
