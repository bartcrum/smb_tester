from throughput.results import BenchmarkResult, ResultSet, MB
from throughput import regression


def r(bucket, seconds, op="write", tool="smb"):
    # 10 MB moved; MB/s = 10/seconds
    return BenchmarkResult(tool=tool, target="t", bucket=bucket, operation=op,
                           bytes_total=10 * MB, ops=10, seconds=seconds)


def test_detects_regression_beyond_threshold():
    baseline = ResultSet([r("1MB", 1.0)])   # 10 MB/s
    current = ResultSet([r("1MB", 2.0)])    # 5 MB/s  (-50%)
    rep = regression.check_regression(current, baseline, threshold_pct=10)
    assert rep.ok is False
    assert len(rep.regressions) == 1
    assert rep.regressions[0]["delta_pct"] == -50.0
    assert "FAIL" in rep.format()


def test_small_drop_within_threshold_passes():
    baseline = ResultSet([r("1MB", 1.0)])      # 10 MB/s
    current = ResultSet([r("1MB", 1.05)])      # ~9.52 MB/s (-4.8%)
    rep = regression.check_regression(current, baseline, threshold_pct=10)
    assert rep.ok is True
    assert len(rep.unchanged) == 1


def test_improvement_classified_not_failed():
    baseline = ResultSet([r("1MB", 2.0)])      # 5 MB/s
    current = ResultSet([r("1MB", 1.0)])       # 10 MB/s (+100%)
    rep = regression.check_regression(current, baseline, threshold_pct=10)
    assert rep.ok is True
    assert len(rep.improvements) == 1


def test_new_result_without_baseline():
    baseline = ResultSet([r("1MB", 1.0)])
    current = ResultSet([r("256MB", 1.0)])
    rep = regression.check_regression(current, baseline)
    assert rep.ok is True
    assert len(rep.missing_baseline) == 1
    assert "NEW" in rep.format()


def test_save_and_load_baseline_roundtrip(tmp_path):
    rs = ResultSet([r("1MB", 1.0), r("4KB", 0.5)])
    p = regression.save_baseline(rs, tmp_path / "base.csv")
    loaded = regression.load_baseline(p)
    rep = regression.check_regression(rs, loaded, threshold_pct=10)
    assert rep.ok is True and len(rep.unchanged) == 2
