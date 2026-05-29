import sqlite3

from throughput.tools import db


def test_run_sqlite_benchmark_insert_and_select():
    rs = db.run_sqlite_benchmark(num_rows=5000, batch_size=500)
    by = {r.operation: r for r in rs}
    assert set(by) == {"insert", "select"}
    assert by["insert"].ops == 5000
    assert by["select"].ops == 5000
    assert by["insert"].tool == "sqlite"
    assert by["insert"].ops_per_s > 0
    assert by["select"].mb_per_s > 0
    assert by["insert"].metadata["batch_size"] == 500


def test_bulk_insert_actually_persists_rows():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    rows = [(i, f"v{i}") for i in range(100)]
    db.bulk_insert(conn, "t", ["a", "b"], rows, batch_size=25)
    count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    assert count == 100


def test_bulk_insert_batches_via_executemany():
    class FakeCursor:
        def __init__(self): self.calls = 0
        def executemany(self, sql, batch): self.calls += 1

    class FakeConn:
        def __init__(self): self.cur = FakeCursor(); self.committed = False
        def cursor(self): return self.cur
        def commit(self): self.committed = True

    conn = FakeConn()
    rows = [(i,) for i in range(250)]
    db.bulk_insert(conn, "t", ["a"], rows, batch_size=100)
    assert conn.cur.calls == 3          # 100 + 100 + 50
    assert conn.committed is True


def test_bulk_read_counts_rows():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (a INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(42)])
    conn.commit()
    rs = db.bulk_read(conn, "SELECT * FROM t")
    assert rs.results[0].ops == 42
    assert rs.results[0].operation == "select"
