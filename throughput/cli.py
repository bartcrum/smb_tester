"""Command-line entry point for the throughput suite.

Exposes the runnable-anywhere tools plus shared export/compare/report flags.
Tool-specific run logic lives in ``throughput.tools``; this only wires argparse
to it and handles output (table + CSV/JSON/HTML), so it stays thin and testable.
"""

from __future__ import annotations

import argparse
import sys

from .buckets import MB
from .results import ResultSet
from . import history, prometheus, regression, report as report_mod
from .tools import filesweep, latency, http_load, db


def format_table(results: ResultSet) -> str:
    if not len(results):
        return "(no results)"
    header = f"{'tool':<10} {'bucket':<8} {'op':<8} {'MB/s':>10} {'ops/s':>12} {'sec':>8}"
    lines = [header, "-" * len(header)]
    for r in results:
        lines.append(f"{r.tool:<10} {r.bucket:<8} {r.operation:<8} "
                     f"{r.mb_per_s:>10g} {r.ops_per_s:>12g} {round(r.seconds, 3):>8g}")
    return "\n".join(lines)


def _emit(results: ResultSet, args) -> None:
    print(format_table(results))
    if getattr(args, "csv", None):
        results.to_csv(args.csv)
        print(f"\nCSV  -> {args.csv}")
    if getattr(args, "json", None):
        results.to_json(args.json)
        print(f"JSON -> {args.json}")
    if getattr(args, "html", None):
        report_mod.write_report(results, args.html)
        print(f"HTML -> {args.html}")
    if getattr(args, "prom", None):
        prometheus.write_prometheus(results, args.prom)
        print(f"PROM -> {args.prom}")


def _add_output_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--csv")
    p.add_argument("--json")
    p.add_argument("--html")
    p.add_argument("--prom", help="write Prometheus text-exposition metrics")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="throughput",
                                     description="File & network throughput benchmarks")
    sub = parser.add_subparsers(dest="cmd", required=True)

    fs = sub.add_parser("filesweep", help="read/write sweep at a path")
    fs.add_argument("path")
    fs.add_argument("--threads", type=int, default=8)
    fs.add_argument("--payload-mb", type=int, default=256)
    fs.add_argument("--no-read", action="store_true")
    _add_output_flags(fs)

    lat = sub.add_parser("latency", help="TCP connect RTT probe")
    lat.add_argument("host")
    lat.add_argument("--port", type=int, default=445)
    lat.add_argument("--count", type=int, default=10)
    _add_output_flags(lat)

    ht = sub.add_parser("http", help="HTTP load test")
    ht.add_argument("url")
    ht.add_argument("--requests", type=int, default=100)
    ht.add_argument("--concurrency", type=int, default=10)
    _add_output_flags(ht)

    dbp = sub.add_parser("db", help="sqlite bulk insert/read benchmark")
    dbp.add_argument("--rows", type=int, default=10000)
    dbp.add_argument("--batch", type=int, default=1000)
    _add_output_flags(dbp)

    rep = sub.add_parser("report", help="render an HTML report from a results CSV")
    rep.add_argument("csv")
    rep.add_argument("--out", required=True)

    cmp = sub.add_parser("compare", help="regression-check a run against a baseline")
    cmp.add_argument("csv")
    cmp.add_argument("--baseline", required=True)
    cmp.add_argument("--threshold", type=float, default=10.0)

    prom = sub.add_parser("prometheus",
                          help="render Prometheus metrics from a results CSV")
    prom.add_argument("csv")
    prom.add_argument("--out", required=True)

    bl = sub.add_parser("baseline",
                        help="continuous per-target baseline history")
    blsub = bl.add_subparsers(dest="baseline_cmd", required=True)
    rec = blsub.add_parser("record", help="append a run CSV to the history store")
    rec.add_argument("csv")
    rec.add_argument("--store", required=True)
    rec.add_argument("--run-id")
    chk = blsub.add_parser("check", help="gate a run CSV against rolling history")
    chk.add_argument("csv")
    chk.add_argument("--store", required=True)
    chk.add_argument("--threshold", type=float, default=10.0)
    chk.add_argument("--window", type=int, default=5)
    chk.add_argument("--agg", choices=["median", "mean", "min", "max"],
                     default="median")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "filesweep":
        rs = filesweep.run_sweep(args.path, threads=args.threads,
                                 total_payload_bytes=args.payload_mb * MB,
                                 do_read=not args.no_read)
        _emit(rs, args)
    elif args.cmd == "latency":
        _emit(latency.tcp_probe(args.host, port=args.port, count=args.count), args)
    elif args.cmd == "http":
        _emit(http_load.run_http_load(args.url, requests=args.requests,
                                      concurrency=args.concurrency), args)
    elif args.cmd == "db":
        _emit(db.run_sqlite_benchmark(num_rows=args.rows, batch_size=args.batch), args)
    elif args.cmd == "report":
        report_mod.write_report(ResultSet.from_csv(args.csv), args.out)
        print(f"HTML -> {args.out}")
    elif args.cmd == "compare":
        rep = regression.check_regression(ResultSet.from_csv(args.csv),
                                          ResultSet.from_csv(args.baseline),
                                          threshold_pct=args.threshold)
        print(rep.format())
        return 0 if rep.ok else 1
    elif args.cmd == "prometheus":
        prometheus.write_prometheus(ResultSet.from_csv(args.csv), args.out)
        print(f"PROM -> {args.out}")
    elif args.cmd == "baseline":
        if args.baseline_cmd == "record":
            path = history.record_run(ResultSet.from_csv(args.csv), args.store,
                                      run_id=args.run_id)
            print(f"recorded -> {path}")
        elif args.baseline_cmd == "check":
            rep = history.check_against_history(
                ResultSet.from_csv(args.csv), args.store,
                threshold_pct=args.threshold, window=args.window, agg=args.agg)
            print(rep.format())
            return 0 if rep.ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
