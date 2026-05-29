"""Common result schema + CSV/JSON exporters + baseline diff.

This is the contract every tool in the suite shares. A single
:class:`BenchmarkResult` is one (tool, target, bucket, operation) measurement.
Throughput (MB/s) and operations/s are *derived* from raw totals so the same
row works for files, requests, messages, or rows.

The small-vs-large (or low-vs-high concurrency) ratio is where the insight
lives, so we always keep both ``bytes_total`` and ``ops`` rather than only a
headline MB/s.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

MB = 1024 * 1024


@dataclass
class BenchmarkResult:
    """A single measurement, comparable across every tool in the suite."""

    tool: str                 # "smb", "iperf3", "s3", "http", ...
    target: str               # what was measured (host, path, url, bucket)
    bucket: str               # size/scenario label, e.g. "1MB", "tcp", "p95"
    operation: str            # "write", "read", "send", "recv", "get", "put"
    bytes_total: int          # total bytes moved in this measurement
    ops: int                  # number of files/requests/messages/rows
    seconds: float            # wall-clock elapsed
    size_bytes: int = 0       # per-op payload size (0 if not applicable)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def mb_per_s(self) -> float:
        return round((self.bytes_total / MB) / max(self.seconds, 1e-9), 3)

    @property
    def ops_per_s(self) -> float:
        return round(self.ops / max(self.seconds, 1e-9), 3)

    # ---- serialization -----------------------------------------------------
    # Flat dict: dataclass fields plus the two derived metrics, with the
    # metadata dict JSON-encoded so it survives a CSV round-trip.
    FLAT_FIELDS = (
        "tool", "target", "bucket", "operation",
        "size_bytes", "bytes_total", "ops", "seconds",
        "mb_per_s", "ops_per_s", "metadata",
    )

    def to_flat(self) -> dict[str, Any]:
        d = asdict(self)
        d["mb_per_s"] = self.mb_per_s
        d["ops_per_s"] = self.ops_per_s
        d["metadata"] = json.dumps(self.metadata, sort_keys=True)
        return {k: d[k] for k in self.FLAT_FIELDS}

    @classmethod
    def from_flat(cls, row: dict[str, Any]) -> "BenchmarkResult":
        meta = row.get("metadata") or "{}"
        if isinstance(meta, str):
            meta = json.loads(meta) if meta.strip() else {}
        return cls(
            tool=row["tool"],
            target=row["target"],
            bucket=row["bucket"],
            operation=row["operation"],
            bytes_total=int(float(row["bytes_total"])),
            ops=int(float(row["ops"])),
            seconds=float(row["seconds"]),
            size_bytes=int(float(row.get("size_bytes", 0) or 0)),
            metadata=meta,
        )

    @property
    def key(self) -> tuple[str, str, str, str]:
        """Identity for diffing one run against another."""
        return (self.tool, self.target, self.bucket, self.operation)


@dataclass
class ResultSet:
    """An ordered collection of results with shared export/diff behavior."""

    results: list[BenchmarkResult] = field(default_factory=list)

    def __iter__(self) -> Iterable[BenchmarkResult]:
        return iter(self.results)

    def __len__(self) -> int:
        return len(self.results)

    def add(self, result: BenchmarkResult) -> None:
        self.results.append(result)

    # ---- exporters ---------------------------------------------------------
    def to_csv(self, path: str | Path) -> Path:
        path = Path(path)
        with path.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(BenchmarkResult.FLAT_FIELDS))
            writer.writeheader()
            for r in self.results:
                writer.writerow(r.to_flat())
        return path

    def to_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(json.dumps([r.to_flat() for r in self.results], indent=2))
        return path

    @classmethod
    def from_csv(cls, path: str | Path) -> "ResultSet":
        path = Path(path)
        with path.open(newline="") as fh:
            rows = list(csv.DictReader(fh))
        return cls([BenchmarkResult.from_flat(r) for r in rows])

    @classmethod
    def from_json(cls, path: str | Path) -> "ResultSet":
        rows = json.loads(Path(path).read_text())
        return cls([BenchmarkResult.from_flat(r) for r in rows])

    # ---- diff --------------------------------------------------------------
    def compare(self, baseline: "ResultSet") -> list[dict[str, Any]]:
        """Diff this run against a baseline by result key.

        Returns one row per current result with the baseline MB/s, current
        MB/s, and percent delta (negative = regression). Results missing from
        the baseline get ``baseline_mb_per_s=None`` and ``delta_pct=None``.
        """
        base_by_key = {r.key: r for r in baseline.results}
        rows: list[dict[str, Any]] = []
        for r in self.results:
            b = base_by_key.get(r.key)
            if b is None:
                rows.append({
                    "tool": r.tool, "target": r.target, "bucket": r.bucket,
                    "operation": r.operation, "baseline_mb_per_s": None,
                    "current_mb_per_s": r.mb_per_s, "delta_pct": None,
                })
                continue
            delta = None
            if b.mb_per_s > 0:
                delta = round((r.mb_per_s - b.mb_per_s) / b.mb_per_s * 100, 2)
            rows.append({
                "tool": r.tool, "target": r.target, "bucket": r.bucket,
                "operation": r.operation, "baseline_mb_per_s": b.mb_per_s,
                "current_mb_per_s": r.mb_per_s, "delta_pct": delta,
            })
        return rows
