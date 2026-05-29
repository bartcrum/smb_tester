import pytest

from throughput import cli
from throughput.results import BenchmarkResult, ResultSet, MB


def test_filesweep_command_runs_and_exports(tmp_path, capsys):
    out_csv = tmp_path / "r.csv"
    rc = cli.main(["filesweep", str(tmp_path), "--threads", "2",
                   "--payload-mb", "1", "--no-read", "--csv", str(out_csv)])
    assert rc == 0
    assert out_csv.exists()
    printed = capsys.readouterr().out
    assert "MB/s" in printed
    assert "CSV  ->" in printed


def test_db_command(capsys):
    rc = cli.main(["db", "--rows", "1000", "--batch", "200"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "insert" in out and "select" in out


def test_report_command_builds_html(tmp_path):
    rs = ResultSet([BenchmarkResult("smb", "t", "1MB", "write", 10 * MB, 10, 2.0)])
    csv = rs.to_csv(tmp_path / "in.csv")
    out = tmp_path / "out.html"
    rc = cli.main(["report", str(csv), "--out", str(out)])
    assert rc == 0
    assert out.read_text().startswith("<!doctype html>")


def test_compare_command_exit_codes(tmp_path):
    base = ResultSet([BenchmarkResult("smb", "t", "1MB", "write", 10 * MB, 10, 1.0)])
    regressed = ResultSet([BenchmarkResult("smb", "t", "1MB", "write", 10 * MB, 10, 2.0)])
    bpath = base.to_csv(tmp_path / "base.csv")
    # passing run (same as baseline)
    cur_ok = base.to_csv(tmp_path / "ok.csv")
    assert cli.main(["compare", str(cur_ok), "--baseline", str(bpath)]) == 0
    # regressed run -> exit 1
    rpath = regressed.to_csv(tmp_path / "bad.csv")
    assert cli.main(["compare", str(rpath), "--baseline", str(bpath),
                     "--threshold", "10"]) == 1


def test_no_subcommand_errors():
    with pytest.raises(SystemExit):
        cli.main([])
