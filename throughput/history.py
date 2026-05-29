"""Continuous baseline storage — per-target run history feeding the gate.

``regression.save_baseline``/``load_baseline`` compares against a single frozen
CSV. For CI you usually want a *rolling* history: keep every run, and gate the
next one against the median of the recent window so one noisy run neither trips
the gate nor silently becomes the new baseline.

The store is just a directory of timestamped result CSVs (the same schema the
rest of the suite uses), so it stays greppable/inspectable and reuses
:class:`ResultSet`'s exporters. ``record`` appends; ``check`` compares the
incoming run against the rolling baseline via the existing regression machinery.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .regression import RegressionReport, check_regression
from .results import MB, BenchmarkResult, ResultSet

_TS_FMT = "%Y%m%dT%H%M%SZ"

_AGGREGATORS: dict[str, Callable[[list[float]], float]] = {
    "median": statistics.median,
    "mean": statistics.fmean,
    "min": min,
    "max": max,
}


def _runs_dir(store: str | Path) -> Path:
    return Path(store) / "runs"


def _safe(token: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in token)


def record_run(results: ResultSet, store: str | Path, *,
               run_id: str | None = None,
               timestamp: datetime | None = None) -> Path:
    """Append ``results`` to the history store as a timestamped CSV."""
    runs = _runs_dir(store)
    runs.mkdir(parents=True, exist_ok=True)
    ts = (timestamp or datetime.now(timezone.utc)).strftime(_TS_FMT)
    stem = f"{ts}__{_safe(run_id or 'run')}"
    path = runs / f"{stem}.csv"
    # Multiple runs can land in the same second; never clobber a prior one.
    n = 1
    while path.exists():
        path = runs / f"{stem}.{n}.csv"
        n += 1
    results.to_csv(path)
    return path


def list_runs(store: str | Path) -> list[Path]:
    """All run CSVs in the store, oldest first (filenames sort by timestamp)."""
    runs = _runs_dir(store)
    if not runs.exists():
        return []
    return sorted(runs.glob("*.csv"))


def latest_baseline(store: str | Path) -> ResultSet | None:
    """The most recent recorded run, or ``None`` if the store is empty."""
    runs = list_runs(store)
    return ResultSet.from_csv(runs[-1]) if runs else None


def rolling_baseline(store: str | Path, *, window: int = 5,
                     agg: str = "median") -> ResultSet | None:
    """Aggregate the last ``window`` runs into one baseline ResultSet.

    For each result key, MB/s is aggregated (``median`` by default) across the
    runs that contain it. The synthesized baseline carries that MB/s (and the
    per-run samples in metadata) so it flows straight through the existing
    ``compare``/``check_regression`` gate, which keys off MB/s.
    """
    runs = list_runs(store)
    if not runs:
        return None
    aggregate = _AGGREGATORS[agg]
    recent = runs[-window:]

    samples: dict[tuple, list[BenchmarkResult]] = {}
    order: list[tuple] = []
    for path in recent:
        for r in ResultSet.from_csv(path):
            if r.key not in samples:
                samples[r.key] = []
                order.append(r.key)
            samples[r.key].append(r)

    out = ResultSet()
    for key in order:
        rows = samples[key]
        values = [r.mb_per_s for r in rows]
        mbps = aggregate(values)
        latest = rows[-1]
        # seconds=1.0 makes mb_per_s == bytes_total/MB == mbps for the gate.
        out.add(BenchmarkResult(
            tool=latest.tool, target=latest.target, bucket=latest.bucket,
            operation=latest.operation, bytes_total=int(round(mbps * MB)),
            ops=latest.ops, seconds=1.0, size_bytes=latest.size_bytes,
            metadata={"baseline_agg": agg, "window": len(rows),
                      "samples_mb_per_s": values},
        ))
    return out


def check_against_history(results: ResultSet, store: str | Path, *,
                          threshold_pct: float = 10.0, window: int = 5,
                          agg: str = "median") -> RegressionReport:
    """Gate ``results`` against the rolling baseline from the store.

    With no history yet, every result is reported as new (the gate passes), so
    the very first CI run can seed the store without failing.
    """
    base = rolling_baseline(store, window=window, agg=agg) or ResultSet()
    return check_regression(results, base, threshold_pct=threshold_pct)


def history_for(store: str | Path,
                key: tuple[str, str, str, str]) -> list[tuple[str, float]]:
    """Time series of ``(timestamp, mb_per_s)`` for one result key."""
    series: list[tuple[str, float]] = []
    for path in list_runs(store):
        ts = path.name.split("__", 1)[0]
        for r in ResultSet.from_csv(path):
            if r.key == key:
                series.append((ts, r.mb_per_s))
                break
    return series
