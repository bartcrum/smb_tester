import pytest

from throughput.tools import transfer

RSYNC_OUT = """
Number of files: 1,000 (reg: 1,000)
Number of regular files transferred: 1,000
Total file size: 1,048,576,000 bytes
Total transferred file size: 1,048,576,000 bytes
Literal data: 1,048,576,000 bytes

sent 1,049,000,000 bytes  received 19,000 bytes  20,980,380.00 bytes/sec
total size is 1,048,576,000  speedup is 1.00
"""


def test_build_rsync_command():
    cmd = transfer.build_rsync_command("/src/", "host:/dst/", compress=True,
                                       extra=["--delete"])
    assert cmd[0] == "rsync" and "--stats" in cmd
    assert "-a" in cmd and "-z" in cmd and "--delete" in cmd
    assert cmd[-2:] == ["/src/", "host:/dst/"]


def test_parse_rsync_stats():
    rs = transfer.parse_rsync_stats(RSYNC_OUT, target="t")
    r = rs.results[0]
    assert r.ops == 1000
    assert r.bytes_total == 1_049_000_000 + 19_000
    # rate ~ 20.98 MB/s -> 1.049e9+19000 bytes / rate seconds
    assert r.metadata["rate_bytes_per_s"] == 20_980_380.0
    assert r.mb_per_s > 0


def test_parse_rsync_stats_missing_summary_raises():
    with pytest.raises(ValueError):
        transfer.parse_rsync_stats("no summary here")


def test_timed_transfer_records_bytes_and_ops():
    called = []
    r = transfer.timed_transfer(lambda: called.append(1), total_bytes=1000,
                                ops=5, tool="ftp", target="t", operation="upload")
    assert called == [1]
    assert r.bytes_total == 1000 and r.ops == 5
    assert r.operation == "upload"


def test_ftp_upload_uses_storbinary():
    class FakeFTP:
        def __init__(self): self.stored = None
        def storbinary(self, cmd, fp): self.stored = (cmd, fp.read())

    ftp = FakeFTP()
    rs = transfer.ftp_upload(ftp, "remote.dat", b"x" * 2048)
    assert ftp.stored[0] == "STOR remote.dat"
    assert rs.results[0].bytes_total == 2048
    assert rs.results[0].tool == "ftp"
