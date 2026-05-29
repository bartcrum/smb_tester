import http.server
import threading

import pytest

from throughput.tools import http_load


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"x" * 1024
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


class _BigHandler(http.server.BaseHTTPRequestHandler):
    BODY = b"y" * (256 * 1024)        # larger than _HTTP_CHUNK (64 KiB)

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.BODY)))
        self.end_headers()
        self.wfile.write(self.BODY)

    def log_message(self, *a):
        pass


@pytest.fixture
def big_server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _BigHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


def test_run_http_load_counts_multichunk_body(big_server):
    # Body spans several _HTTP_CHUNK reads: the chunked drain must total it all.
    rs = http_load.run_http_load(big_server, requests=4, concurrency=2)
    r = rs.results[0]
    assert r.bytes_total == 4 * 256 * 1024


def test_run_http_load_real_server(server):
    rs = http_load.run_http_load(server, requests=20, concurrency=5)
    r = rs.results[0]
    assert r.ops == 20
    assert r.bytes_total == 20 * 1024
    assert r.metadata["statuses"] == {200: 20}
    assert r.ops_per_s > 0
    assert r.metadata["p95_ms"] is not None


WRK_OUT = """Running 10s test @ http://localhost/
  4 threads and 100 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    12.34ms    5.67ms  100.00ms   80.00%
    Req/Sec     2.50k   500.00     3.00k    75.00%
  100000 requests in 10.00s, 50.00MB read
Requests/sec:  10000.00
Transfer/sec:      5.00MB
"""


def test_parse_wrk():
    rs = http_load.parse_wrk(WRK_OUT)
    r = rs.results[0]
    assert r.ops == 100000
    assert r.seconds == pytest.approx(10.0)
    assert r.bytes_total == 50 * 1024**2
    assert r.metadata["avg_ms"] == pytest.approx(12.34, abs=0.01)
    assert r.ops_per_s == pytest.approx(10000.0, abs=1)


def test_parse_wrk_bad_input():
    with pytest.raises(ValueError):
        http_load.parse_wrk("nothing useful")


def test_parse_k6_summary():
    data = {"metrics": {
        "http_reqs": {"count": 5000, "rate": 500.0},
        "data_received": {"count": 10_000_000},
        "http_req_duration": {"avg": 8.5, "p(95)": 20.1},
    }}
    rs = http_load.parse_k6_summary(data)
    r = rs.results[0]
    assert r.ops == 5000
    assert r.seconds == pytest.approx(10.0)     # 5000 / 500
    assert r.metadata["p95_ms"] == 20.1
