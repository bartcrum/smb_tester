# smb_tester

A small toolkit for measuring storage and network service throughput. The
first tool is a PowerShell SMB throughput sweep that profiles read/write
performance across a range of file sizes, exposing the small-file vs
large-file overhead curve.

This repo is intended to grow into a broader **throughput / performance
benchmarking suite** as we scale to other file and network services — see
[Roadmap: other tools to add](#roadmap-other-tools-to-add) below.

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

## Roadmap: other tools to add

As we scale to other file and network services, these are natural additions to
keep this repo a one-stop throughput/perf toolkit. Grouped by layer:

### Network-layer (raw bandwidth & latency)

- **`iperf3` wrapper** — raw TCP/UDP line-rate baseline to compare against
  protocol-level results above. Knowing your raw ceiling makes the SMB
  "protocol-bound vs bandwidth-bound" call unambiguous.
- **Latency/jitter probe** — wrap `ping` / `Test-Connection` / `psping` to
  capture RTT distribution and packet loss over time, not just an average.
- **MTU / path-MTU discovery** — detect fragmentation that silently caps
  throughput.

### File / object storage protocols

- **NFS throughput sweep** — Linux/NFS analog of the SMB tool (`fio` or `dd`
  driven) so we can compare SMB vs NFS on the same NAS.
- **S3 / object-store benchmark** — parallel `PUT`/`GET` across object sizes
  using the AWS SDK or `s3-benchmark` / `warp` (MinIO). Same small-vs-large
  curve, but for object stores; surfaces per-object request overhead and
  multipart thresholds.
- **Azure Blob / Files & GCS benchmarks** — analogous wrappers as we touch more
  clouds; reuse the bucketed-payload + CSV-compare pattern.
- **Local disk baseline (`fio` / `diskspd`)** — isolate storage from network by
  benchmarking the target's local disk directly, so we can attribute slowness
  to wire vs spindle/SSD.
- **FTP/SFTP/rsync throughput** — for transfer-oriented services and migration
  planning.

### Application / service layer

- **HTTP(S) throughput & latency** — wrap `wrk`, `k6`, or `hey` for REST/object
  download endpoints; reuse the size-bucket idea for payload sweeps.
- **Database bulk I/O** — bulk insert / bulk read throughput for SQL/NoSQL
  targets as we onboard data-heavy apps.
- **Message-queue throughput** — Kafka / RabbitMQ / SQS producer-consumer
  rates, again across message sizes.

### Shared infrastructure (build once, reuse everywhere)

- **Common results schema + CSV/JSON exporters** — every tool emits the same
  shape (`bucket, size, MB/s, ops/s, seconds`) so cross-tool comparison and the
  existing `-CompareWith` diff logic work everywhere.
- **Baseline/regression harness** — store baselines per target and fail CI (or
  alert) when throughput regresses beyond a threshold.
- **Dashboard / report generator** — render sweep CSVs into the small-vs-large
  curve charts (HTML or Grafana) instead of eyeballing tables.
- **Orchestrator** — one entry point that runs the relevant probes against a
  named target and produces a single comparison report (raw iperf vs SMB vs NFS
  vs disk), making the bottleneck obvious at a glance.

---

## Contributing

New benchmarks should follow the conventions established by the SMB tool:

- **Constant total payload per bucket** so size buckets are directly comparable.
- **Report both throughput (MB/s) and operations/s** — the ratio between
  small and large is where the insight lives.
- **Emit CSV** with a comparable schema and support a `-CompareWith` baseline.
- **Print connection/context diagnostics** up front (protocol version, latency,
  relevant capabilities) and **degrade gracefully** when diagnostics aren't
  available on the target.
