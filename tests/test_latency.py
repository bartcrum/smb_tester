import pytest

from throughput.tools import latency


def test_summarize_distribution_and_jitter():
    s = latency.summarize([10.0, 12.0, 11.0, 50.0, 10.0])
    assert s["min_ms"] == 10.0
    assert s["max_ms"] == 50.0
    assert s["received"] == 5 and s["loss_pct"] == 0.0
    assert s["p95_ms"] == 50.0
    assert s["jitter_ms"] > 0  # consecutive deltas present


def test_summarize_counts_loss():
    s = latency.summarize([10.0, None, 12.0, None])
    assert s["sent"] == 4 and s["received"] == 2
    assert s["loss_pct"] == 50.0


def test_summarize_all_lost():
    s = latency.summarize([None, None])
    assert s["received"] == 0 and s["loss_pct"] == 100.0
    assert s["avg_ms"] is None


def test_probe_uses_injected_connect_fn():
    seq = iter([5.0, 7.0, None, 6.0])
    rs = latency.probe("host:445", lambda: next(seq), count=4)
    r = rs.results[0]
    assert r.metadata["sent"] == 4
    assert r.metadata["received"] == 3
    assert r.metadata["loss_pct"] == 25.0
    assert r.operation == "connect"


def test_tcp_probe_against_local_listener():
    import socket
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)  # hold unaccepted connects in the queue
    port = srv.getsockname()[1]
    try:
        rs = latency.tcp_probe("127.0.0.1", port=port, count=3)
    finally:
        srv.close()
    r = rs.results[0]
    assert r.metadata["received"] == 3
    assert r.metadata["loss_pct"] == 0.0
    assert r.metadata["avg_ms"] is not None


def test_parse_ping_linux_output():
    out = (
        "PING host (10.0.0.1) 56(84) bytes of data.\n"
        "--- host ping statistics ---\n"
        "4 packets transmitted, 4 received, 0% packet loss, time 3005ms\n"
        "rtt min/avg/max/mdev = 0.512/0.701/0.998/0.180 ms\n"
    )
    rs = latency.parse_ping(out, target="host")
    s = rs.results[0].metadata
    assert s["loss_pct"] == 0.0
    assert s["avg_ms"] == 0.701
    assert s["jitter_ms"] == 0.180
