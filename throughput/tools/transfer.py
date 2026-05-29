"""Bulk-transfer throughput: rsync (primary), plus FTP/SFTP helpers.

For migration planning and transfer-oriented services. rsync is wrapped with a
``--stats`` parser; FTP/SFTP reuse a generic timed-transfer core that takes an
injected client, so the timing logic is testable without a live server.
"""

from __future__ import annotations

import re
import time

from ..results import BenchmarkResult, ResultSet


# ----------------------------------------------------------------------- rsync
def build_rsync_command(src: str, dst: str, *, archive: bool = True,
                        compress: bool = False, extra: list[str] | None = None
                        ) -> list[str]:
    cmd = ["rsync", "--stats"]
    if archive:
        cmd.append("-a")
    if compress:
        cmd.append("-z")
    cmd += (extra or [])
    cmd += [src, dst]
    return cmd


_SENT_RE = re.compile(
    r"sent\s+([\d,]+)\s+bytes\s+received\s+([\d,]+)\s+bytes\s+([\d,.]+)\s+bytes/sec")
_FILES_RE = re.compile(r"Number of regular files transferred:\s*([\d,]+)")


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_rsync_stats(output: str, target: str = "rsync") -> ResultSet:
    sent_m = _SENT_RE.search(output)
    if not sent_m:
        raise ValueError("could not find rsync --stats summary line")
    sent, received, rate = (_num(sent_m.group(1)), _num(sent_m.group(2)),
                            _num(sent_m.group(3)))
    total = sent + received
    seconds = total / max(rate, 1e-9)
    files_m = _FILES_RE.search(output)
    files = int(_num(files_m.group(1))) if files_m else 1
    return ResultSet([BenchmarkResult(
        tool="rsync", target=target, bucket="transfer", operation="send",
        bytes_total=int(total), ops=max(files, 1), seconds=max(seconds, 1e-9),
        metadata={"sent_bytes": int(sent), "received_bytes": int(received),
                  "rate_bytes_per_s": rate},
    )])


def run_rsync(src: str, dst: str, **kw) -> ResultSet:
    from ._proc import require, run_capture
    require("rsync")
    out = run_capture(build_rsync_command(src, dst, **kw), timeout=None)
    return parse_rsync_stats(out, target=f"{src} -> {dst}")


# ------------------------------------------------------------------- FTP/SFTP
def timed_transfer(transfer_fn, total_bytes: int, ops: int, *,
                   tool: str, target: str, operation: str) -> BenchmarkResult:
    """Time ``transfer_fn()`` (which moves ``total_bytes`` over ``ops`` files)."""
    start = time.perf_counter()
    transfer_fn()
    seconds = max(time.perf_counter() - start, 1e-9)
    return BenchmarkResult(
        tool=tool, target=target, bucket="transfer", operation=operation,
        bytes_total=total_bytes, ops=ops, seconds=seconds,
    )


def ftp_upload(ftp, remote_name: str, data: bytes, *, target: str = "ftp"
               ) -> ResultSet:
    """Upload ``data`` via a connected ftplib.FTP and measure throughput."""
    import io

    def do():
        ftp.storbinary(f"STOR {remote_name}", io.BytesIO(data))

    return ResultSet([timed_transfer(do, len(data), 1, tool="ftp",
                                     target=target, operation="upload")])


def sftp_upload(sftp_client, remote_path: str, data: bytes, *,
                target: str = "sftp") -> ResultSet:
    """Upload ``data`` via a paramiko SFTPClient and measure throughput."""
    def do():
        with sftp_client.open(remote_path, "wb") as fh:
            fh.write(data)

    return ResultSet([timed_transfer(do, len(data), 1, tool="sftp",
                                     target=target, operation="upload")])
