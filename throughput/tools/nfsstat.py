"""NFS connection context — the NFS analog of the SMB tool's diagnostics.

The SMB sweep reports the negotiated dialect, signing/encryption, and RTT next
to its throughput numbers because those *explain* the numbers. The NFS
equivalents are:

* the negotiated **protocol version** (``vers=4.2``), **transport**
  (``proto=tcp``), and **rsize/wsize** — the big drivers of large-file
  streaming, and
* the client **RPC retransmit rate** — a driver of small-op latency, the way
  RTT is for SMB.

Pure parsers for ``nfsstat -m`` (mount options) and ``nfsstat -c`` (client RPC
stats), unit-tested against captured output, plus a thin :func:`collect_context`
that shells out. Like the SMB tool's diagnostics, it degrades gracefully when
``nfsstat`` is unavailable (e.g. a non-Linux client) rather than failing a run.
"""

from __future__ import annotations

import re
from typing import Any

# A mount header line: "<mountpoint> from <server>:<export>".
_MOUNT_RE = re.compile(r"^(\S+)\s+from\s+(.+?):(.+)$")
# The flags line that follows it: " Flags: rw,vers=4.2,rsize=...".
_FLAGS_RE = re.compile(r"^\s*Flags:\s*(.+)$")

# These mount options get coerced to int for easy charting/labelling.
_INT_OPTS = ("rsize", "wsize", "timeo", "retrans", "acregmin", "acregmax",
             "namlen", "port", "mountport")


def _parse_flags(flags: str) -> dict[str, Any]:
    opts: dict[str, Any] = {}
    for token in flags.split(","):
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            k, v = token.split("=", 1)
            opts[k] = int(v) if (k in _INT_OPTS and v.isdigit()) else v
        else:
            opts[token] = True
    return opts


def parse_nfs_mounts(output: str) -> dict[str, dict[str, Any]]:
    """Parse ``nfsstat -m`` into ``{mountpoint: {server, export, options}}``."""
    mounts: dict[str, dict[str, Any]] = {}
    current: str | None = None
    for line in output.splitlines():
        m = _MOUNT_RE.match(line)
        if m:
            current = m.group(1)
            mounts[current] = {"server": m.group(2), "export": m.group(3),
                               "options": {}}
            continue
        f = _FLAGS_RE.match(line)
        if f and current is not None:
            mounts[current]["options"] = _parse_flags(f.group(1))
    return mounts


# "Client rpc stats:" then a header row then a values row.
_RPC_HEADER = re.compile(r"^\s*calls\b")


def parse_nfsstat_client(output: str) -> dict[str, Any]:
    """Parse ``nfsstat -c`` client RPC stats (calls/retrans + retrans %)."""
    lines = output.splitlines()
    for i, line in enumerate(lines):
        if _RPC_HEADER.match(line) and i + 1 < len(lines):
            headers = line.split()
            values = lines[i + 1].split()
            if not values or not values[0].isdigit():
                continue
            stats: dict[str, Any] = {}
            for h, v in zip(headers, values):
                try:
                    stats[h] = int(v)
                except ValueError:
                    stats[h] = v
            calls = stats.get("calls", 0)
            retrans = stats.get("retrans", 0)
            stats["retrans_pct"] = (round(retrans / calls * 100, 3)
                                    if calls else 0.0)
            return stats
    return {}


def _match_mountpoint(mounts: dict[str, dict], mountpoint: str | None):
    if mountpoint is None:
        return mounts
    norm = mountpoint.rstrip("/")
    return {k: v for k, v in mounts.items() if k.rstrip("/") == norm} or mounts


def collect_context(mountpoint: str | None = None) -> dict[str, Any] | None:
    """Shell out to ``nfsstat`` and return merged mount + RPC context.

    Returns ``None`` if ``nfsstat`` isn't on PATH (so callers can degrade
    gracefully). When ``mountpoint`` is given, mount options are filtered to it.
    """
    from ._proc import ToolNotFound, require, run_capture

    try:
        require("nfsstat")
    except ToolNotFound:
        return None

    ctx: dict[str, Any] = {}
    try:
        ctx["mounts"] = _match_mountpoint(
            parse_nfs_mounts(run_capture(["nfsstat", "-m"])), mountpoint)
    except Exception:
        ctx["mounts"] = {}
    try:
        ctx["rpc"] = parse_nfsstat_client(run_capture(["nfsstat", "-c"]))
    except Exception:
        ctx["rpc"] = {}
    return ctx
