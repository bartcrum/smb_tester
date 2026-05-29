"""Baseline & regression harness.

Store a baseline run per target and fail (CI) or alert when throughput
regresses beyond a threshold. Built on :meth:`ResultSet.compare`, so it works
uniformly across every tool in the suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .results import ResultSet


@dataclass
class RegressionReport:
    ok: bool
    threshold_pct: float
    regressions: list[dict] = field(default_factory=list)
    improvements: list[dict] = field(default_factory=list)
    unchanged: list[dict] = field(default_factory=list)
    missing_baseline: list[dict] = field(default_factory=list)

    def format(self) -> str:
        lines = [f"Regression check (threshold {self.threshold_pct}%): "
                 f"{'PASS' if self.ok else 'FAIL'}"]
        for r in self.regressions:
            lines.append(f"  REGRESSION {r['tool']}/{r['bucket']}/{r['operation']}: "
                         f"{r['baseline_mb_per_s']} -> {r['current_mb_per_s']} MB/s "
                         f"({r['delta_pct']}%)")
        for r in self.missing_baseline:
            lines.append(f"  NEW {r['tool']}/{r['bucket']}/{r['operation']}: "
                         f"{r['current_mb_per_s']} MB/s (no baseline)")
        return "\n".join(lines)


def check_regression(current: ResultSet, baseline: ResultSet, *,
                     threshold_pct: float = 10.0) -> RegressionReport:
    """Flag results whose MB/s dropped more than ``threshold_pct`` vs baseline."""
    rows = current.compare(baseline)
    report = RegressionReport(ok=True, threshold_pct=threshold_pct)
    for row in rows:
        delta = row["delta_pct"]
        if delta is None:
            report.missing_baseline.append(row)
        elif delta <= -threshold_pct:
            report.regressions.append(row)
            report.ok = False
        elif delta >= threshold_pct:
            report.improvements.append(row)
        else:
            report.unchanged.append(row)
    return report


def save_baseline(results: ResultSet, path: str | Path) -> Path:
    return results.to_csv(path)


def load_baseline(path: str | Path) -> ResultSet:
    return ResultSet.from_csv(path)
