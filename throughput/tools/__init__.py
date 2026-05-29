"""Individual benchmark tools. Each builds :class:`~throughput.results.ResultSet`.

Tools that wrap an external binary (iperf3, fio, rsync, ...) keep command
construction and output parsing as pure functions so they're unit-testable
without the binary installed; the ``run*`` helpers shell out and require it.
"""
