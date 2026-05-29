"""Prometheus text-exposition export (with a matching Grafana dashboard).

A second output target alongside the static HTML report: turn any
:class:`ResultSet` into the Prometheus text exposition format so a run can be

* dropped into the node_exporter **textfile collector** directory
  (:func:`write_prometheus` writes atomically, the way the collector expects), or
* shipped to a Pushgateway / scraped from a file by anything that speaks the
  text format.

Dependency-free — it only formats text, mirroring ``report.py``. Every measure
becomes a gauge labelled by ``tool``/``target``/``bucket``/``operation`` so the
small-vs-large curve is a single PromQL query, and latency stats carried in
result metadata are exported under ``<ns>_latency_ms{stat="p95",...}``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .results import BenchmarkResult, ResultSet

NAMESPACE = "throughput"

# (metric suffix, HELP text, value extractor). Order is the emit order; all
# samples of one family are grouped under a single HELP/TYPE, as Prometheus
# requires.
_METRICS = (
    ("mb_per_s", "Throughput in MB/s (derived from bytes_total / seconds).",
     lambda r: r.mb_per_s),
    ("ops_per_s", "Operations per second (files/requests/messages/rows).",
     lambda r: r.ops_per_s),
    ("bytes_total", "Total bytes moved in the measurement.",
     lambda r: r.bytes_total),
    ("ops", "Operation count for the measurement.",
     lambda r: r.ops),
    ("seconds", "Wall-clock seconds for the measurement.",
     lambda r: round(r.seconds, 6)),
)

# Latency-ish metadata, exported as <ns>_latency_ms{...,stat="<name>"} when a
# numeric value is present. The "_ms" suffix is dropped from the stat label.
_LATENCY_STATS = ("min_ms", "avg_ms", "p50_ms", "p95_ms", "max_ms", "jitter_ms")


def _escape(value: str) -> str:
    """Escape a Prometheus label value (backslash, quote, newline)."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt(value) -> str:
    # Keep ints integral; let floats render without locale/grouping surprises.
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _labels(r: BenchmarkResult, extra: dict | None = None) -> str:
    pairs = {"tool": r.tool, "target": r.target,
             "bucket": r.bucket, "operation": r.operation}
    if extra:
        pairs.update(extra)
    body = ",".join(f'{k}="{_escape(str(v))}"' for k, v in pairs.items())
    return "{" + body + "}"


def render_prometheus(results: ResultSet, *, namespace: str = NAMESPACE) -> str:
    """Render results as Prometheus text exposition format."""
    lines: list[str] = []
    for suffix, help_text, extract in _METRICS:
        name = f"{namespace}_{suffix}"
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        for r in results:
            lines.append(f"{name}{_labels(r)} {_fmt(extract(r))}")

    lat_name = f"{namespace}_latency_ms"
    lat_samples: list[str] = []
    for r in results:
        for stat in _LATENCY_STATS:
            v = r.metadata.get(stat)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                lat_samples.append(
                    f'{lat_name}{_labels(r, {"stat": stat[:-3]})} {_fmt(v)}')
    if lat_samples:
        lines.append(f"# HELP {lat_name} Latency stats from result metadata "
                     f"(milliseconds).")
        lines.append(f"# TYPE {lat_name} gauge")
        lines.extend(lat_samples)

    return "\n".join(lines) + "\n"


def write_prometheus(results: ResultSet, path: str | Path, *,
                     namespace: str = NAMESPACE) -> Path:
    """Write the exposition text to ``path`` atomically (collector-safe).

    node_exporter's textfile collector may read the file mid-write, so render
    to a temp file in the same directory and ``os.replace`` it into place.
    """
    path = Path(path)
    text = render_prometheus(results, namespace=namespace)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent or "."), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        # Don't leave a stray temp file behind if the replace never happened.
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path
