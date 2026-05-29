<#
.SYNOPSIS
    SMB throughput sweep tool. Measures read and write performance across a
    range of file sizes over an SMB/UNC path, exposing the small-file vs
    large-file overhead curve.

.DESCRIPTION
    Unlike iperf (raw TCP/UDP), this exercises the full SMB protocol stack:
    CREATE / WRITE / READ / CLOSE round-trips. Small files are dominated by
    operations-per-second (latency/IOPS bound); large files reveal streaming
    bandwidth. The gap between them tells you where your bottleneck is.

    Reports MB/s AND files/s per size bucket, plus the negotiated SMB dialect
    and connection details (important when the target is a NAS, which may cap
    the dialect and lack multichannel/encryption).

.PARAMETER TargetPath
    UNC path to a writable directory on the target, e.g. \\nas01\share\smbtest.
    A subfolder is created here and cleaned up afterward.

.PARAMETER Threads
    Parallel streams (mimics iperf -P). Requires PowerShell 7+. Default 8.

.PARAMETER TotalPayloadMB
    Total data moved per size bucket. Kept constant across buckets so the
    comparison is fair (same bytes, different granularity). Default 2048 (2 GB).

.PARAMETER Sizes
    Hashtable of label = bytes to sweep. Defaults cover 4KB..256MB.

.PARAMETER SkipRead
    Only run the write test.

.PARAMETER CsvPath
    Write per-bucket results to this CSV. Use the same file with -CompareWith
    on a later run to diff.

.PARAMETER CompareWith
    Path to a previous CSV. Prints a side-by-side delta against this run.

.PARAMETER DropFirstBucket
    Discard the smallest bucket's result as warmup (SMB session setup happens
    on the first op). The bucket still runs; its numbers are flagged.

.EXAMPLE
    .\Invoke-SmbThroughputSweep.ps1 -TargetPath \\nas01\share\smbtest -CsvPath nas_run1.csv

.EXAMPLE
    .\Invoke-SmbThroughputSweep.ps1 -TargetPath \\nas01\share\smbtest -CompareWith nas_run1.csv

.NOTES
    Disk-vs-wire: writing real files puts the target's storage in the loop. To
    isolate the network, point -TargetPath at a RAM-backed share on the target
    (ImDisk on Windows). For reads, files small enough to sit in the target's
    cache approximate pure-path throughput. Be consistent about cold vs warm.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$TargetPath,

    [int]$Threads = 8,

    [int]$TotalPayloadMB = 2048,

    [hashtable]$Sizes = @{
        "4KB"   = 4KB
        "16KB"  = 16KB
        "64KB"  = 64KB
        "256KB" = 256KB
        "1MB"   = 1MB
        "16MB"  = 16MB
        "256MB" = 256MB
    },

    [switch]$SkipRead,

    [string]$CsvPath,

    [string]$CompareWith,

    [switch]$DropFirstBucket
)

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ required (uses ForEach-Object -Parallel). Current: $($PSVersionTable.PSVersion)"
}

$ErrorActionPreference = 'Stop'
$totalPayloadBytes = [int64]$TotalPayloadMB * 1MB

# ---------------------------------------------------------------------------
# Connection context
# ---------------------------------------------------------------------------
function Get-ServerName([string]$unc) {
    if ($unc -match '^\\\\([^\\]+)\\') { return $Matches[1] }
    return $null
}

function Show-ConnectionContext([string]$unc) {
    $server = Get-ServerName $unc
    Write-Host ""
    Write-Host "=== SMB connection context ===" -ForegroundColor Cyan

    # Ensure a connection exists so Get-SmbConnection has something to report.
    try { [System.IO.Directory]::Exists($unc) | Out-Null } catch {}

    try {
        $conn = Get-SmbConnection -ServerName $server -ErrorAction Stop |
                Select-Object -First 1
        if ($conn) {
            Write-Host ("Server          : {0}" -f $conn.ServerName)
            Write-Host ("Share           : {0}" -f $conn.ShareName)
            Write-Host ("SMB dialect     : {0}" -f $conn.Dialect)
            Write-Host ("Signed          : {0}" -f $conn.Signed)
            Write-Host ("Encrypted       : {0}" -f $conn.Encrypted)
            Write-Host ("Continuously av.: {0}" -f $conn.ContinuouslyAvailable)
        }
    } catch {
        Write-Host "Get-SmbConnection unavailable yet (will populate after first op)." -ForegroundColor DarkYellow
    }

    try {
        $mc = Get-SmbMultichannelConnection -ServerName $server -ErrorAction Stop
        if ($mc) {
            Write-Host ("Multichannel    : {0} active connection(s)" -f @($mc).Count)
        } else {
            Write-Host "Multichannel    : none (single channel)"
        }
    } catch {
        Write-Host "Multichannel    : not reported (common on NAS targets)" -ForegroundColor DarkYellow
    }

    # Round-trip latency — the single biggest driver of small-file rates.
    if ($server) {
        try {
            $p = Test-Connection -TargetName $server -Count 4 -ErrorAction Stop
            $avg = ($p | Measure-Object -Property Latency -Average).Average
            Write-Host ("Avg RTT         : {0} ms" -f ([math]::Round($avg,2)))
        } catch {
            Write-Host "Avg RTT         : ping blocked/unavailable" -ForegroundColor DarkYellow
        }
    }
    Write-Host ""
}

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------
function Invoke-SizeBucket {
    param(
        [string]$Label,
        [int64]$FileSize,
        [string]$Dir,
        [int64]$TotalBytes,
        [int]$ThreadCount,
        [switch]$RunRead
    )

    $count  = [math]::Max(1, [int]($TotalBytes / $FileSize))
    $buffer = New-Object byte[] $FileSize
    (New-Object Random).NextBytes($buffer)

    # ---- WRITE ----
    $swW = [System.Diagnostics.Stopwatch]::StartNew()
    1..$count | ForEach-Object -ThrottleLimit $ThreadCount -Parallel {
        $f = Join-Path $using:Dir ("f_{0}.dat" -f $_)
        [System.IO.File]::WriteAllBytes($f, $using:buffer)
    }
    $swW.Stop()
    $secW  = [math]::Max($swW.Elapsed.TotalSeconds, 0.0001)
    $mbW   = ($FileSize * $count) / 1MB

    # ---- READ ----
    $secR = $null; $mbR = $null
    if ($RunRead) {
        $swR = [System.Diagnostics.Stopwatch]::StartNew()
        1..$count | ForEach-Object -ThrottleLimit $ThreadCount -Parallel {
            $f = Join-Path $using:Dir ("f_{0}.dat" -f $_)
            [void][System.IO.File]::ReadAllBytes($f)
        }
        $swR.Stop()
        $secR = [math]::Max($swR.Elapsed.TotalSeconds, 0.0001)
        $mbR  = ($FileSize * $count) / 1MB
    }

    # cleanup this bucket
    Get-ChildItem $Dir -Filter "f_*.dat" -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue

    [pscustomobject]@{
        Bucket        = $Label
        FileSizeBytes = $FileSize
        Files         = $count
        WriteMBps     = [math]::Round($mbW / $secW, 1)
        WriteFilesPS  = [math]::Round($count / $secW, 0)
        WriteSec      = [math]::Round($secW, 2)
        ReadMBps      = if ($null -ne $secR) { [math]::Round($mbR / $secR, 1) } else { $null }
        ReadFilesPS   = if ($null -ne $secR) { [math]::Round($count / $secR, 0) } else { $null }
        ReadSec       = if ($null -ne $secR) { [math]::Round($secR, 2) } else { $null }
    }
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
$testDir = Join-Path $TargetPath ("sweep_{0}" -f ([guid]::NewGuid().ToString('N').Substring(0,8)))
New-Item -ItemType Directory -Force -Path $testDir | Out-Null

Show-ConnectionContext $TargetPath

Write-Host "=== Throughput sweep ===" -ForegroundColor Cyan
Write-Host ("Target   : {0}" -f $testDir)
Write-Host ("Threads  : {0}    Payload/bucket: {1} MB" -f $Threads, $TotalPayloadMB)
Write-Host ("Read test: {0}" -f (-not $SkipRead))
Write-Host ""

$header = "{0,-7} | {1,9} | {2,9} | {3,10} | {4,9} | {5,10}" -f `
    "Bucket","Files","Wr MB/s","Wr files/s","Rd MB/s","Rd files/s"
Write-Host $header
Write-Host ("-" * $header.Length)

$results = @()
$orderedLabels = $Sizes.Keys | Sort-Object { [int64]$Sizes[$_] }
$first = $true

foreach ($label in $orderedLabels) {
    $r = Invoke-SizeBucket -Label $label -FileSize ([int64]$Sizes[$label]) `
            -Dir $testDir -TotalBytes $totalPayloadBytes -ThreadCount $Threads `
            -RunRead:(-not $SkipRead)

    $warm = ($first -and $DropFirstBucket)
    if ($warm) { $r | Add-Member -NotePropertyName Warmup -NotePropertyValue $true }

    $rd  = if ($null -ne $r.ReadMBps)    { $r.ReadMBps }    else { "-" }
    $rdf = if ($null -ne $r.ReadFilesPS) { $r.ReadFilesPS } else { "-" }
    $flag = if ($warm) { "  (warmup)" } else { "" }

    Write-Host ("{0,-7} | {1,9} | {2,9} | {3,10} | {4,9} | {5,10}{6}" -f `
        $r.Bucket, $r.Files, $r.WriteMBps, $r.WriteFilesPS, $rd, $rdf, $flag)

    $results += $r
    $first = $false
}

# cleanup test dir
Remove-Item $testDir -Recurse -Force -ErrorAction SilentlyContinue

# ---------------------------------------------------------------------------
# Interpretation hint
# ---------------------------------------------------------------------------
$small = $results | Where-Object { -not $_.Warmup } | Sort-Object FileSizeBytes | Select-Object -First 1
$large = $results | Sort-Object FileSizeBytes | Select-Object -Last 1
if ($small -and $large -and $large.WriteMBps -gt 0) {
    $ratio = [math]::Round($large.WriteMBps / [math]::Max($small.WriteMBps,0.1), 1)
    Write-Host ""
    Write-Host ("Large/small write throughput ratio: {0}x ({1} -> {2})" -f `
        $ratio, $small.Bucket, $large.Bucket) -ForegroundColor Green
    Write-Host "High ratio = small files are overhead/latency bound (per-file CREATE/CLOSE RTT)."
    Write-Host "Large files near NIC line rate but small files crawl => protocol/metadata bound, not bandwidth."
}

# ---------------------------------------------------------------------------
# CSV out
# ---------------------------------------------------------------------------
if ($CsvPath) {
    $results | Select-Object Bucket,FileSizeBytes,Files,WriteMBps,WriteFilesPS,WriteSec,ReadMBps,ReadFilesPS,ReadSec |
        Export-Csv -Path $CsvPath -NoTypeInformation
    Write-Host ""
    Write-Host ("Results written: {0}" -f $CsvPath) -ForegroundColor Cyan
}

# ---------------------------------------------------------------------------
# Compare mode
# ---------------------------------------------------------------------------
if ($CompareWith) {
    if (-not (Test-Path $CompareWith)) {
        Write-Warning "CompareWith file not found: $CompareWith"
    } else {
        $prev = Import-Csv $CompareWith
        Write-Host ""
        Write-Host ("=== Delta vs {0} ===" -f $CompareWith) -ForegroundColor Cyan
        $ch = "{0,-7} | {1,12} | {2,12} | {3,8}" -f "Bucket","Prev Wr MB/s","Now Wr MB/s","Delta%"
        Write-Host $ch
        Write-Host ("-" * $ch.Length)
        foreach ($r in ($results | Sort-Object FileSizeBytes)) {
            $p = $prev | Where-Object Bucket -eq $r.Bucket | Select-Object -First 1
            if ($p) {
                $pv = [double]$p.WriteMBps
                $delta = if ($pv -gt 0) { [math]::Round((($r.WriteMBps - $pv) / $pv) * 100, 1) } else { 0 }
                $sign = if ($delta -ge 0) { "+" } else { "" }
                Write-Host ("{0,-7} | {1,12} | {2,12} | {3,7}" -f `
                    $r.Bucket, $pv, $r.WriteMBps, ("{0}{1}%" -f $sign,$delta))
            }
        }
    }
}