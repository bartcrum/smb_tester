import pytest

from throughput.tools import disk

FIO_JSON = {
    "jobs": [{
        "jobname": "bench",
        "job options": {"bs": "1M", "filename": "/mnt/data/test"},
        "read": {"bw_bytes": 524_288_000, "iops": 500.0, "runtime": 10000,
                 "lat_ns": {"mean": 2_000_000}},
        "write": {"bw_bytes": 262_144_000, "iops": 250.0, "runtime": 10000,
                  "lat_ns": {"mean": 4_000_000}},
    }]
}

DISKSPD_TEXT = """
Read IO
thread |       bytes     |     I/Os |    MiB/s |  I/O per s |
------------------------------------------------------------
total:        524288000 |    500   |   50.00  |    50.00   |

Write IO
thread |       bytes     |     I/Os |    MiB/s |  I/O per s |
------------------------------------------------------------
total:        262144000 |    250   |   25.00  |    25.00   |
"""


def test_build_fio_command():
    cmd = disk.build_fio_command("/mnt/x", rw="randread", bs="4k", size="2G",
                                 direct=True, runtime=30)
    assert "--rw=randread" in cmd and "--bs=4k" in cmd
    assert "--direct=1" in cmd and "--time_based" in cmd
    assert "--output-format=json" in cmd


def test_parse_fio_read_and_write():
    rs = disk.parse_fio(FIO_JSON)
    by = {r.operation: r for r in rs}
    assert set(by) == {"read", "write"}
    assert by["read"].bucket == "1M"
    assert by["read"].target == "/mnt/data/test"
    # 524_288_000 bytes/s == 500 MiB/s
    assert by["read"].mb_per_s == pytest.approx(500.0, abs=0.1)
    assert by["read"].metadata["iops"] == 500.0


def test_parse_fio_skips_empty_section():
    data = {"jobs": [{"jobname": "j", "job options": {"bs": "4k"},
                      "read": {"bw_bytes": 0, "iops": 0, "runtime": 0},
                      "write": {"bw_bytes": 1000, "iops": 1, "runtime": 1000}}]}
    rs = disk.parse_fio(data)
    assert {r.operation for r in rs} == {"write"}


def test_parse_diskspd_read_write():
    rs = disk.parse_diskspd(DISKSPD_TEXT, target="C:\\test")
    by = {r.operation: r for r in rs}
    assert set(by) == {"read", "write"}
    assert by["read"].mb_per_s == pytest.approx(50.0, abs=0.1)
    assert by["write"].metadata["iops"] == 25.0
