from throughput.results import BenchmarkResult, ResultSet, MB
from throughput import report


def make():
    return ResultSet([
        BenchmarkResult("smb", "\\\\nas\\s", "4KB", "write", 1 * MB, 256, 2.0, 4096),
        BenchmarkResult("smb", "\\\\nas\\s", "256MB", "write", 256 * MB, 1, 1.0, 256 * MB),
        BenchmarkResult("iperf3", "10.0.0.5", "tcp", "send", 1250 * MB, 1, 10.0),
    ])


def test_render_html_contains_data_and_structure():
    out = report.render_html(make(), title="My Run")
    assert "<!doctype html>" in out
    assert "My Run" in out
    assert "<svg" in out and "<table>" in out
    assert "smb" in out and "iperf3" in out
    assert "4KB" in out and "256MB" in out
    assert "3 measurement(s)" in out


def test_render_html_escapes_unc_paths():
    rs = ResultSet([BenchmarkResult("smb", "t", "<b>x</b>", "write",
                                    MB, 1, 1.0, MB)])
    out = report.render_html(rs)
    assert "<b>x</b>" not in out          # bucket label escaped
    assert "&lt;b&gt;x&lt;/b&gt;" in out


def test_render_html_empty():
    out = report.render_html(ResultSet())
    assert "No results." in out


def test_write_report_creates_file(tmp_path):
    p = report.write_report(make(), tmp_path / "r.html")
    assert p.exists()
    assert p.read_text().startswith("<!doctype html>")
