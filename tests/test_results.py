import json

from throughput.results import BenchmarkResult, ResultSet, MB


def make(tool="smb", bucket="1MB", op="write", bytes_total=10 * MB, ops=10, seconds=2.0, **md):
    return BenchmarkResult(
        tool=tool, target="\\\\nas01\\share", bucket=bucket, operation=op,
        bytes_total=bytes_total, ops=ops, seconds=seconds, size_bytes=MB,
        metadata=md,
    )


def test_derived_metrics():
    r = make(bytes_total=10 * MB, ops=10, seconds=2.0)
    assert r.mb_per_s == 5.0          # 10 MB / 2 s
    assert r.ops_per_s == 5.0         # 10 ops / 2 s


def test_derived_metrics_guard_zero_seconds():
    r = make(seconds=0.0)
    # no ZeroDivisionError; huge but finite
    assert r.mb_per_s > 0
    assert r.ops_per_s > 0


def test_flat_roundtrip_preserves_metadata():
    r = make(dialect="3.1.1", encrypted=True)
    flat = r.to_flat()
    assert isinstance(flat["metadata"], str)            # JSON-encoded for CSV
    assert json.loads(flat["metadata"])["dialect"] == "3.1.1"
    back = BenchmarkResult.from_flat(flat)
    assert back.metadata == {"dialect": "3.1.1", "encrypted": True}
    assert back.bytes_total == r.bytes_total
    assert back.key == r.key


def test_csv_roundtrip(tmp_path):
    rs = ResultSet([make(bucket="4KB"), make(bucket="1MB", seconds=1.0)])
    p = rs.to_csv(tmp_path / "out.csv")
    loaded = ResultSet.from_csv(p)
    assert len(loaded) == 2
    assert [r.bucket for r in loaded] == ["4KB", "1MB"]
    assert loaded.results[1].mb_per_s == 10.0


def test_json_roundtrip(tmp_path):
    rs = ResultSet([make(), make(op="read")])
    p = rs.to_json(tmp_path / "out.json")
    loaded = ResultSet.from_json(p)
    assert {r.operation for r in loaded} == {"write", "read"}


def test_compare_reports_delta_and_regression():
    baseline = ResultSet([make(bucket="1MB", bytes_total=10 * MB, seconds=2.0)])  # 5 MB/s
    current = ResultSet([make(bucket="1MB", bytes_total=10 * MB, seconds=4.0)])   # 2.5 MB/s
    diff = current.compare(baseline)
    assert len(diff) == 1
    row = diff[0]
    assert row["baseline_mb_per_s"] == 5.0
    assert row["current_mb_per_s"] == 2.5
    assert row["delta_pct"] == -50.0


def test_compare_handles_missing_baseline_key():
    baseline = ResultSet([make(bucket="1MB")])
    current = ResultSet([make(bucket="256MB")])
    diff = current.compare(baseline)
    assert diff[0]["baseline_mb_per_s"] is None
    assert diff[0]["delta_pct"] is None
