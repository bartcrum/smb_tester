# smb_tester

A toolkit for measuring storage and network service throughput. It started as
a PowerShell SMB throughput sweep and has grown into a cross-platform
**Python benchmarking suite** (`throughput/`) that profiles read/write/transfer
performance across a range of payload sizes for many services — always exposing
the small-vs-large overhead curve and emitting one comparable result shape.

- **[`invoke_smb_throughput_test.ps1`](#invoke_smb_throughput_testps1)** — the
  original Windows-native SMB sweep.
- **[`throughput/` Python suite](#throughput-python-suite)** — iperf3, latency,
  MTU, filesystem/NFS, fio/diskspd, S3/Azure/GCS, rsync/FTP/SFTP, HTTP, DB, and
  message-queue benchmarks, plus a shared results schema, regression harness,
  HTML report generator, orchestrator, and CLI.

---

## `invoke_smb_throughput_test.ps1`

Measures **read and write performance** across a sweep of file sizes over an
SMB/UNC path. Unlike `iperf` (which measures raw TCP/UDP), this exercises the
full SMB protocol stack — `CREATE` / `WRITE` / `READ` / `CLOSE` round-trips —
so it tells you where your real-world bottleneck is:

- **Small files** are dominated by operations-per-second (latency / IOPS bound).
- **Large files** reveal streaming bandwidth (closer to NIC line rate).
- **The gap between them** tells you whether you are bandwidth-bound or
  protocol/metadata/latency-bound.

For each size bucket the script reports **MB/s** and **files/s**, plus the
negotiated SMB dialect and connection details (signing, encryption,
multichannel, RTT) — which matter a lot when the target is a NAS that may cap
the dialect or lack multichannel.

### Requirements

- **PowerShell 7+** — uses `ForEach-Object -Parallel` for multi-stream tests.
  Check with `$PSVersionTable.PSVersion`.
- A **writable directory** on the SMB target (a temp subfolder is created and
  cleaned up automatically).
- The `SmbShare` module for connection diagnostics (ships with Windows;
  diagnostics degrade gracefully if unavailable, e.g. on a NAS).

### Quick start

```powershell
# Basic sweep against a share
.\invoke_smb_throughput_test.ps1 -TargetPath \\nas01\share\smbtest

# Save results to CSV for later comparison
.\invoke_smb_throughput_test.ps1 -TargetPath \\nas01\share\smbtest -CsvPath nas_run1.csv

# Re-run later and diff against the saved baseline
.\invoke_smb_throughput_test.ps1 -TargetPath \\nas01\share\smbtest -CompareWith nas_run1.csv

# Write-only, more parallel streams, smaller payload per bucket
.\invoke_smb_throughput_test.ps1 -TargetPath \\nas01\share\smbtest -SkipRead -Threads 16 -TotalPayloadMB 512
```

### Parameters

| Parameter          | Type        | Default            | Description |
|--------------------|-------------|--------------------|-------------|
| `-TargetPath`      | string (req) | —                 | UNC path to a writable directory, e.g. `\\nas01\share\smbtest`. A subfolder is created here and removed afterward. |
| `-Threads`         | int         | `8`                | Parallel streams (mimics `iperf -P`). Requires PowerShell 7+. |
| `-TotalPayloadMB`  | int         | `2048` (2 GB)      | Total data moved **per size bucket**. Held constant across buckets so comparisons are fair (same bytes, different granularity). |
| `-Sizes`           | hashtable   | `4KB`–`256MB`      | `label = bytes` map of buckets to sweep. |
| `-SkipRead`        | switch      | off                | Run the write test only. |
| `-CsvPath`         | string      | —                  | Write per-bucket results to this CSV. |
| `-CompareWith`     | string      | —                  | Path to a previous CSV; prints a side-by-side write-throughput delta. |
| `-DropFirstBucket` | switch      | off                | Flag the smallest bucket as warmup (SMB session setup happens on the first op). The bucket still runs; its numbers are marked. |

Default buckets: `4KB`, `16KB`, `64KB`, `256KB`, `1MB`, `16MB`, `256MB`.

Custom sweep example:

```powershell
.\invoke_smb_throughput_test.ps1 -TargetPath \\nas01\share\smbtest -Sizes @{
    "8KB"  = 8KB
    "128KB" = 128KB
    "4MB"  = 4MB
    "64MB" = 64MB
}
```

### Reading the output

The script prints three things:

1. **SMB connection context** — server, share, negotiated dialect, signing,
   encryption, multichannel status, and average RTT. RTT is the single biggest
   driver of small-file rates.
2. **The sweep table** — `Wr MB/s`, `Wr files/s`, `Rd MB/s`, `Rd files/s` per
   bucket.
3. **Interpretation hint** — the *large/small write throughput ratio*. A high
   ratio means small files are overhead/latency bound (per-file CREATE/CLOSE
   RTT). If large files run near NIC line rate but small files crawl, you are
   **protocol/metadata bound, not bandwidth bound** — adding bandwidth won't
   help; reducing round-trips (batching, larger files, lower latency, SMB
   multichannel) will.

### Disk-vs-wire caveat

Writing real files puts the target's **storage** in the loop, not just the
network. To isolate the network path:

- Point `-TargetPath` at a **RAM-backed share** on the target (e.g. ImDisk on
  Windows).
- For reads, use files small enough to sit in the target's cache to approximate
  pure-path throughput.
- Be consistent about **cold vs warm** cache between runs you intend to compare.

### Note on filename

The script's `.EXAMPLE` blocks refer to `Invoke-SmbThroughputSweep.ps1` (a
verb-noun PowerShell-idiomatic name). The file currently lives as
`invoke_smb_throughput_test.ps1`; use whichever name matches your checkout.

---

## `throughput/` Python suite

A cross-platform Python package that extends the SMB tool's approach to many
services. Every benchmark emits the same
[`BenchmarkResult`](throughput/results.py) shape — `tool, target, bucket,
operation, bytes_total, ops, seconds` (+ derived `mb_per_s` / `ops_per_s`) — so
results from any tool are directly comparable, export to the same CSV/JSON, and
flow through the shared regression/report/orchestrator machinery.

### Install & test

```bash
pip install -e .            # installs the `throughput` console script
pip install -e .[dev]       # + pytest
pytest                      # 79 tests, fully runnable without external binaries
```

Optional extras pull in heavy SDKs only when needed: `pip install -e .[s3]`
(boto3). Azure/GCS/Kafka adapters lazy-import their SDKs, so the suite imports
and tests fine without them.

### Design

Tools that wrap an external binary (iperf3, fio, rsync, wrk/k6, diskspd) keep
**command building and output parsing as pure functions**, unit-tested against
captured sample output — so the parsers are verified even where the binary
isn't installed. The `run*` helpers shell out and require the binary at runtime.
Pure-Python tools (filesystem sweep, latency, HTTP load, sqlite DB, in-memory
queue) actually move bytes and are exercised end-to-end in the tests.

### Tools

| Area | Module | What it does | Status |
|------|--------|--------------|--------|
| Network | [`tools/iperf3.py`](throughput/tools/iperf3.py) | Raw TCP/UDP line-rate baseline (`iperf3 -J` parser) | ✅ |
| Network | [`tools/latency.py`](throughput/tools/latency.py) | RTT distribution + jitter + loss (TCP connect probe / `ping` parser) | ✅ |
| Network | [`tools/mtu.py`](throughput/tools/mtu.py) | Path-MTU discovery (binary search + `ping` DF probe) | ✅ |
| Storage | [`tools/filesweep.py`](throughput/tools/filesweep.py) | Parallel read/write sweep for NFS / mounted shares / local disk | ✅ |
| Storage | [`tools/disk.py`](throughput/tools/disk.py) | Local disk baseline (`fio` JSON + `diskspd` text parsers) | ✅ |
| Storage | [`tools/objectstore.py`](throughput/tools/objectstore.py) | Object PUT/GET sweep — S3 / Azure Blob / GCS adapters | ✅ |
| Storage | [`tools/transfer.py`](throughput/tools/transfer.py) | Bulk transfer — `rsync --stats` parser + FTP/SFTP timing | ✅ |
| App | [`tools/http_load.py`](throughput/tools/http_load.py) | HTTP(S) throughput & latency (pure-Python load + `wrk`/`k6` parsers) | ✅ |
| App | [`tools/db.py`](throughput/tools/db.py) | DB bulk insert/read (DB-API generic; sqlite built in) | ✅ |
| App | [`tools/mq.py`](throughput/tools/mq.py) | Message-queue produce/consume — Kafka / SQS adapters | ✅ |
| Shared | [`results.py`](throughput/results.py) | Common result schema + CSV/JSON export + baseline diff | ✅ |
| Shared | [`buckets.py`](throughput/buckets.py) | Constant-payload size-bucket sweep helper | ✅ |
| Shared | [`regression.py`](throughput/regression.py) | Baseline store + fail-on-regression check (CI gate) | ✅ |
| Shared | [`report.py`](throughput/report.py) | Self-contained HTML report with inline-SVG bar charts | ✅ |
| Shared | [`orchestrator.py`](throughput/orchestrator.py) | Run a plan of probes → one merged result (failures non-fatal) | ✅ |
| Shared | [`cli.py`](throughput/cli.py) | `throughput` CLI: run / report / compare | ✅ |

### CLI usage

```bash
# Filesystem read/write sweep at a path (NFS/SMB mount or local), export CSV+HTML
throughput filesweep /mnt/nas --threads 16 --payload-mb 512 --csv run.csv --html run.html

# TCP connect-latency probe (default port 445 = SMB)
throughput latency nas01 --port 445 --count 20

# HTTP load test
throughput http https://api.example.com/health --requests 1000 --concurrency 50

# sqlite bulk insert/read micro-benchmark
throughput db --rows 100000 --batch 2000

# Render an HTML report from any results CSV
throughput report run.csv --out run.html

# Regression-gate a run against a baseline (exit 1 if MB/s drops > threshold%)
throughput compare run.csv --baseline baseline.csv --threshold 10
```

### Programmatic usage

```python
from throughput import ResultSet
from throughput.orchestrator import run_plan
from throughput.report import write_report
from throughput.regression import check_regression, load_baseline

# Run raw bandwidth, SMB-mount, and local-disk probes in one pass
plan = [
    {"tool": "iperf3",    "args": {"host": "10.0.0.5"}},
    {"tool": "filesweep", "args": {"path": "/mnt/nas", "tool": "smb"}},
    {"tool": "filesweep", "args": {"path": "/tmp",     "tool": "disk"}},
]
result = run_plan(plan)            # failing probes are captured, not fatal
write_report(result.results, "report.html")

report = check_regression(result.results, load_baseline("baseline.csv"))
print(report.format())            # PASS/FAIL with per-bucket deltas
```

### Roadmap / not yet done

The core surface is in place. Natural follow-ups:

- **Grafana / Prometheus export** alongside the static HTML report.
- **Live adapters validated against real backends** (MinIO for S3, a local
  RabbitMQ/Kafka) in an integration test tier, gated behind a marker so the
  default `pytest` run stays binary-free.
- **`hey`/`vegeta` HTTP parsers** and **NFS-specific `nfsstat` context** to
  mirror the SMB tool's connection diagnostics.
- **Continuous baseline storage** (per-target history) feeding the regression
  gate in CI.

---

## Contributing

New benchmarks should follow the conventions the suite is built on:

- **Constant total payload per bucket** (see `buckets.py`) so size buckets are
  directly comparable.
- **Emit `BenchmarkResult`** — report raw `bytes_total` and `ops` and let MB/s
  and ops/s derive from them; the small-vs-large ratio is where the insight
  lives.
- **Reuse the shared exporters and diff** (`ResultSet.to_csv/from_csv`,
  `compare`) so `regression`, `report`, and the orchestrator work for free.
- **Keep binary wrappers pure-then-shell**: a pure `build_command` + `parse`
  pair (unit-tested against captured output) and a thin `run*` that shells out,
  so tests don't need the binary installed.
- **Add tests** that pass under a plain `pytest` run with no external services.
