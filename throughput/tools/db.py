"""Database bulk I/O throughput — bulk insert and bulk read.

Generic over any DB-API 2.0 connection (sqlite3, psycopg2, pymysql, ...) since
they share ``cursor``/``executemany``/``fetchall``. sqlite3 (stdlib) gives a
fully runnable, tested path here; the same functions drive a real Postgres/MySQL
connection unchanged.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Sequence

from ..results import BenchmarkResult, ResultSet

# Above this row count we size from a sample and extrapolate rather than
# stringify+encode every cell — that O(rows×cols) pass allocates a throwaway
# str and bytes per value, heavy transient CPU/memory on the host for large
# result sets (the figure is only a reporting metric, not a timed quantity).
_SAMPLE_ROWS = 2000


def _measure_rows(rows: Sequence[Sequence]) -> int:
    total = 0
    for row in rows:
        for v in row:
            total += len(str(v).encode("utf-8")) if v is not None else 0
    return total


def _row_bytes(rows: Sequence[Sequence]) -> int:
    n = len(rows)
    if n <= _SAMPLE_ROWS:
        return _measure_rows(rows)
    sampled = _measure_rows(rows[:_SAMPLE_ROWS])
    return int(round(sampled * n / _SAMPLE_ROWS))


def bulk_insert(conn, table: str, columns: Sequence[str],
                rows: Sequence[Sequence], *, batch_size: int = 1000,
                tool: str = "db", target: str = "db") -> ResultSet:
    """Insert ``rows`` in batches via ``executemany`` and time the lot."""
    placeholders = ", ".join(["?"] * len(columns))
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    cur = conn.cursor()
    nbytes = _row_bytes(rows)
    start = time.perf_counter()
    for i in range(0, len(rows), batch_size):
        cur.executemany(sql, rows[i:i + batch_size])
    conn.commit()
    seconds = max(time.perf_counter() - start, 1e-9)
    return ResultSet([BenchmarkResult(
        tool=tool, target=target, bucket="bulk", operation="insert",
        bytes_total=nbytes, ops=len(rows), seconds=seconds,
        metadata={"batch_size": batch_size},
    )])


def bulk_read(conn, query: str, *, tool: str = "db", target: str = "db"
              ) -> ResultSet:
    """Run ``query``, fetch all rows, and time it."""
    cur = conn.cursor()
    start = time.perf_counter()
    cur.execute(query)
    rows = cur.fetchall()
    seconds = max(time.perf_counter() - start, 1e-9)
    return ResultSet([BenchmarkResult(
        tool=tool, target=target, bucket="bulk", operation="select",
        bytes_total=_row_bytes(rows), ops=len(rows), seconds=seconds,
    )])


def run_sqlite_benchmark(num_rows: int = 10_000, batch_size: int = 1000
                         ) -> ResultSet:
    """In-memory sqlite insert+read benchmark (self-contained, no external DB)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE bench (id INTEGER PRIMARY KEY, name TEXT, val REAL)")
    rows = [(i, f"name-{i}", i * 1.5) for i in range(num_rows)]
    rs = ResultSet()
    for r in bulk_insert(conn, "bench", ["id", "name", "val"], rows,
                         batch_size=batch_size, tool="sqlite", target=":memory:"):
        rs.add(r)
    for r in bulk_read(conn, "SELECT * FROM bench", tool="sqlite",
                       target=":memory:"):
        rs.add(r)
    conn.close()
    return rs
