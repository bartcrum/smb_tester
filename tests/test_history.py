from datetime import datetime, timezone

from throughput import history
from throughput.results import BenchmarkResult, ResultSet, MB


def run(seconds, *, bucket="1MB", op="write", tool="smb"):
    # 10 MB moved -> MB/s = 10 / seconds
    return ResultSet([BenchmarkResult(tool, "t", bucket, op, 10 * MB, 10, seconds)])


def ts(day):
    return datetime(2026, 1, day, tzinfo=timezone.utc)


def test_record_and_list_runs_sorted(tmp_path):
    history.record_run(run(1.0), tmp_path, run_id="b", timestamp=ts(2))
    history.record_run(run(1.0), tmp_path, run_id="a", timestamp=ts(1))
    runs = history.list_runs(tmp_path)
    assert len(runs) == 2
    # oldest (day 1) first regardless of insertion order
    assert "20260101" in runs[0].name and "20260102" in runs[1].name


def test_record_does_not_clobber_same_second(tmp_path):
    history.record_run(run(1.0), tmp_path, run_id="x", timestamp=ts(1))
    history.record_run(run(2.0), tmp_path, run_id="x", timestamp=ts(1))
    assert len(history.list_runs(tmp_path)) == 2


def test_latest_baseline_is_most_recent(tmp_path):
    history.record_run(run(1.0), tmp_path, timestamp=ts(1))   # 10 MB/s
    history.record_run(run(2.0), tmp_path, timestamp=ts(2))   # 5 MB/s
    base = history.latest_baseline(tmp_path)
    assert base.results[0].mb_per_s == 5.0


def test_rolling_baseline_uses_median_over_window(tmp_path):
    for day, secs in [(1, 1.0), (2, 2.0), (3, 1.0)]:   # 10, 5, 10 MB/s
        history.record_run(run(secs), tmp_path, timestamp=ts(day))
    base = history.rolling_baseline(tmp_path, window=3, agg="median")
    r = base.results[0]
    assert r.mb_per_s == 10.0           # median(10, 5, 10)
    assert r.metadata["window"] == 3
    assert sorted(r.metadata["samples_mb_per_s"]) == [5.0, 10.0, 10.0]


def test_rolling_baseline_window_truncates(tmp_path):
    for day, secs in [(1, 1.0), (2, 1.0), (3, 4.0)]:   # 10, 10, 2.5 MB/s
        history.record_run(run(secs), tmp_path, timestamp=ts(day))
    base = history.rolling_baseline(tmp_path, window=2, agg="median")
    # only the last two runs (10, 2.5) -> median 6.25
    assert base.results[0].mb_per_s == 6.25


def test_check_against_history_flags_regression(tmp_path):
    for day in (1, 2):
        history.record_run(run(1.0), tmp_path, timestamp=ts(day))   # 10 MB/s
    rep = history.check_against_history(run(2.0), tmp_path, threshold_pct=10)
    assert rep.ok is False
    assert len(rep.regressions) == 1


def test_check_against_empty_history_passes_as_new(tmp_path):
    rep = history.check_against_history(run(1.0), tmp_path)
    assert rep.ok is True
    assert len(rep.missing_baseline) == 1


def test_history_for_returns_time_series(tmp_path):
    history.record_run(run(1.0), tmp_path, timestamp=ts(1))   # 10 MB/s
    history.record_run(run(2.0), tmp_path, timestamp=ts(2))   # 5 MB/s
    key = ("smb", "t", "1MB", "write")
    series = history.history_for(tmp_path, key)
    assert [v for _, v in series] == [10.0, 5.0]
    assert series[0][0].startswith("20260101")
