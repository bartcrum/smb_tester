import json

import pytest

from throughput.tools import iperf3
from throughput.tools._proc import ToolNotFound

TCP_JSON = {
    "start": {"connecting_to": {"host": "10.0.0.5"},
              "test_start": {"protocol": "TCP"}},
    "end": {
        "sum_sent": {"bytes": 1_250_000_000, "seconds": 10.0,
                     "bits_per_second": 1_000_000_000, "retransmits": 12},
        "sum_received": {"bytes": 1_240_000_000, "seconds": 10.0,
                         "bits_per_second": 992_000_000},
    },
}

UDP_JSON = {
    "start": {"connecting_to": {"host": "10.0.0.5"},
              "test_start": {"protocol": "UDP"}},
    "end": {"sum": {"bytes": 100_000_000, "seconds": 10.0, "packets": 76000,
                    "bits_per_second": 80_000_000, "jitter_ms": 0.25,
                    "lost_packets": 5, "lost_percent": 0.006}},
}


def test_build_command_tcp_defaults():
    cmd = iperf3.build_command("host1")
    assert cmd[:3] == ["iperf3", "-c", "host1"]
    assert "-J" in cmd and "-u" not in cmd and "-R" not in cmd


def test_build_command_udp_reverse_bitrate():
    cmd = iperf3.build_command("h", udp=True, reverse=True, bitrate="100M", parallel=4)
    assert "-u" in cmd and "-R" in cmd
    assert cmd[cmd.index("-b") + 1] == "100M"
    assert cmd[cmd.index("-P") + 1] == "4"


def test_parse_tcp_send_and_recv():
    rs = iperf3.parse(TCP_JSON)
    ops = {r.operation: r for r in rs}
    assert set(ops) == {"send", "recv"}
    # 1.25e9 bytes / 10s = 119.2 MB/s
    assert ops["send"].mb_per_s == pytest.approx(119.2, abs=0.5)
    assert ops["send"].metadata["retransmits"] == 12
    assert ops["send"].bucket == "tcp"
    assert ops["send"].target == "10.0.0.5"


def test_parse_accepts_json_string():
    rs = iperf3.parse(json.dumps(TCP_JSON), target="override")
    assert all(r.target == "override" for r in rs)


def test_parse_udp_keeps_jitter_and_loss():
    rs = iperf3.parse(UDP_JSON)
    assert len(rs) == 1
    r = rs.results[0]
    assert r.bucket == "udp"
    assert r.metadata["jitter_ms"] == 0.25
    assert r.metadata["lost_packets"] == 5


def test_run_without_binary_raises(monkeypatch):
    monkeypatch.setattr("throughput.tools.iperf3.require",
                        lambda b: (_ for _ in ()).throw(ToolNotFound(b)))
    with pytest.raises(ToolNotFound):
        iperf3.run("nohost")
