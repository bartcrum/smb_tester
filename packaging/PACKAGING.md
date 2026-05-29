# Packaging for Windows clients (no Python required)

This produces a single self-contained **`throughput.exe`** that bundles a Python
runtime plus the full suite — including the boto3 / Azure / GCS / Kafka SDKs —
so an end client can run the benchmarks with nothing installed. It also covers
shipping the native SMB PowerShell sweep alongside it.

There are two artifacts in this repo with different requirements:

| Artifact | Needs on the client |
|----------|---------------------|
| `throughput.exe` (built here) | **Nothing** — Python is embedded. |
| `invoke_smb_throughput_test.ps1` | **PowerShell 7+** (uses `ForEach-Object -Parallel`). Native; no Python. |

---

## Building `throughput.exe`

> PyInstaller is **not** a cross-compiler — build the Windows exe **on Windows**
> (a Windows VM/runner is fine). The build needs the same Python *minor* version
> you want embedded; 3.11 is a good default.

From the repo root, on a Windows host:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\activate
pip install -e .[build]          # suite + PyInstaller + all cloud SDKs
pyinstaller packaging\throughput.spec
```

Result: **`dist\throughput.exe`**. Smoke-test it:

```powershell
.\dist\throughput.exe db --rows 50000
.\dist\throughput.exe latency nas01 --port 445 --count 20
.\dist\throughput.exe filesweep \\nas01\share\smbtest --html run.html
```

### Core-only (smaller) exe

The spec bundles whichever cloud SDKs are present in the build env and skips the
rest. For a lean, core-only build, install without the cloud extras and run the
same spec:

```powershell
pip install -e . pyinstaller
pyinstaller packaging\throughput.spec   # prints "skipping boto3 ..." etc.
```

### Notes / troubleshooting

- **Size:** the core-only exe is ~10–15 MB; with all cloud SDKs expect
  ~60–90 MB (boto3/botocore data files dominate). That's normal for onefile.
- **Lazy imports:** the adapters import their SDKs lazily, so the spec pulls
  them in explicitly (`collect_all`). If you add a new backend, add its package
  to the loop in `packaging/throughput.spec`.
- **UPX:** the spec sets `upx=True`; if UPX isn't installed it's silently
  ignored. Install UPX to shrink the exe further, or set `upx=False`.
- **SmartScreen / AV:** unsigned onefile exes can trip Windows SmartScreen and
  some AV heuristics. For wide distribution, code-sign `throughput.exe` with an
  Authenticode certificate.

---

## Shipping the SMB PowerShell sweep alongside

`invoke_smb_throughput_test.ps1` is the original Windows-native SMB throughput
tool and does **not** go inside the exe (it's a script, run by PowerShell, not
Python). Ship it next to the exe.

Assemble a client bundle, e.g.:

```
throughput-windows/
  throughput.exe                     # the Python suite, self-contained
  invoke_smb_throughput_test.ps1     # native SMB sweep
  README-CLIENT.txt                  # the two snippets below
```

### Client usage — `throughput.exe`

```powershell
# Filesystem read/write sweep over an SMB/NFS mount or local path
.\throughput.exe filesweep \\nas01\share\smbtest --threads 16 --html run.html

# TCP connect-latency to the SMB port
.\throughput.exe latency nas01 --port 445 --count 20

# S3 / Azure / GCS / Kafka work too (credentials via the usual env/SDK config)
```

### Client usage — `invoke_smb_throughput_test.ps1`

Requires **PowerShell 7+** (`$PSVersionTable.PSVersion`). On stock Windows
PowerShell 5.1 the parallel sweep won't run — install PowerShell 7 from
<https://aka.ms/powershell>.

```powershell
# Unblock the downloaded script, then run a sweep against a writable share
Unblock-File .\invoke_smb_throughput_test.ps1
pwsh -File .\invoke_smb_throughput_test.ps1 -TargetPath \\nas01\share\smbtest

# If the local execution policy blocks it, scope a bypass to this process only:
pwsh -ExecutionPolicy Bypass -File .\invoke_smb_throughput_test.ps1 `
    -TargetPath \\nas01\share\smbtest -CsvPath nas_run1.csv
```

See the main [README](../README.md#invoke_smb_throughput_testps1) for the full
parameter set and how to read the output.
