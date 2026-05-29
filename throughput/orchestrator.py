"""Orchestrator — run several probes against a target, one combined report.

Make the bottleneck obvious by running, say, raw iperf3 vs SMB/NFS vs local
disk in one pass and merging into a single :class:`ResultSet`. A failing probe
(missing binary, unreachable target) is captured, not fatal, so the rest of the
plan still runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .results import ResultSet
from .tools import (iperf3, latency, mtu, filesweep, disk, objectstore,
                    transfer, http_load, db, mq)

# Default probe registry: name -> callable returning a ResultSet.
PROBES: dict[str, Callable[..., ResultSet]] = {
    "iperf3": iperf3.run,
    "latency": latency.tcp_probe,
    "mtu": mtu.path_mtu,
    "filesweep": filesweep.run_sweep,
    "nfs": filesweep.run_nfs,
    "disk": disk.run_fio,
    "s3": objectstore.run_s3,
    "rsync": transfer.run_rsync,
    "http": http_load.run_http_load,
    "sqlite": db.run_sqlite_benchmark,
}


@dataclass
class PlanResult:
    results: ResultSet = field(default_factory=ResultSet)
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def run_plan(steps: list[dict[str, Any]],
             registry: dict[str, Callable[..., ResultSet]] | None = None
             ) -> PlanResult:
    """Run each ``{"tool": name, "args": {...}}`` step, merging results.

    Unknown tools and probe exceptions are recorded in ``errors``; successful
    probes still contribute their measurements.
    """
    registry = registry if registry is not None else PROBES
    out = PlanResult()
    for step in steps:
        name = step.get("tool")
        args = step.get("args", {})
        fn = registry.get(name)
        if fn is None:
            out.errors.append({"tool": name, "error": "unknown probe"})
            continue
        try:
            rs = fn(**args)
            for r in rs:
                out.results.add(r)
        except Exception as exc:  # noqa: BLE001 - one probe must not sink the plan
            out.errors.append({"tool": name, "error": f"{type(exc).__name__}: {exc}"})
    return out
