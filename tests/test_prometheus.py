from throughput import prometheus
from throughput.results import BenchmarkResult, ResultSet, MB


def _rs():
    return ResultSet([
        BenchmarkResult("smb", "//nas/share", "1MB", "write", 10 * MB, 10, 2.0,
                        size_bytes=MB),
        BenchmarkResult("latency", "nas:445", "rtt", "connect", 0, 20, 0.5,
                        metadata={"p50_ms": 1.2, "p95_ms": 4.5, "avg_ms": 2.0}),
    ])


def test_render_has_help_type_and_samples():
    text = prometheus.render_prometheus(_rs())
    assert "# HELP throughput_mb_per_s" in text
    assert "# TYPE throughput_mb_per_s gauge" in text
    # 10 MB / 2 s = 5 MB/s on the smb write row
    assert 'throughput_mb_per_s{tool="smb",target="//nas/share",' \
           'bucket="1MB",operation="write"} 5.0' in text
    assert text.endswith("\n")


def test_latency_metadata_exported_with_stat_label():
    text = prometheus.render_prometheus(_rs())
    assert "# TYPE throughput_latency_ms gauge" in text
    assert 'throughput_latency_ms{tool="latency",target="nas:445",' \
           'bucket="rtt",operation="connect",stat="p95"} 4.5' in text
    # only stats present in metadata are emitted (no max_ms here)
    assert 'stat="max"' not in text


def test_label_values_are_escaped():
    rs = ResultSet([BenchmarkResult('http', 'http://h/?q="x"\\y', "load",
                                    "get", 0, 1, 1.0)])
    text = prometheus.render_prometheus(rs)
    assert r'target="http://h/?q=\"x\"\\y"' in text


def test_custom_namespace():
    text = prometheus.render_prometheus(_rs(), namespace="bench")
    assert "bench_mb_per_s" in text
    assert "throughput_mb_per_s" not in text


def test_write_prometheus_atomic(tmp_path):
    out = tmp_path / "metrics.prom"
    prometheus.write_prometheus(_rs(), out)
    assert out.read_text() == prometheus.render_prometheus(_rs())
    # no stray temp files left in the directory
    assert [p.name for p in tmp_path.iterdir()] == ["metrics.prom"]
