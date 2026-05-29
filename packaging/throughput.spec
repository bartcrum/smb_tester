# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a self-contained Windows ``throughput.exe``.

Builds the full "core + cloud" CLI: the pure-Python suite plus the boto3 /
azure-storage-blob / google-cloud-storage / confluent-kafka SDKs so S3, Azure
Blob, GCS and Kafka work from the single exe with no Python on the client.

Build (on a Windows host, from the repo root):

    py -3.11 -m venv .venv && .venv\\Scripts\\activate
    pip install -e .[build]
    pyinstaller packaging\\throughput.spec

Output: ``dist\\throughput.exe``. See packaging/PACKAGING.md for assembling the
client bundle (exe + the SMB PowerShell script).

The cloud SDKs are *lazy-imported* by the adapters, so PyInstaller's static
analysis can't see them — we pull each in explicitly with ``collect_all`` and
grab every ``throughput.*`` submodule with ``collect_submodules``. Any SDK that
isn't installed in the build env is skipped, so this same spec also produces a
core-only exe if you ``pip install -e .[build]`` minus the cloud packages.
"""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.dirname(SPECPATH)  # repo root; this spec lives in packaging/
ENTRY = os.path.join(SPECPATH, "throughput_launch.py")

datas, binaries, hiddenimports = [], [], []

# Cloud SDKs — bundled if present in the build environment, skipped otherwise.
for pkg in ("boto3", "botocore", "azure.storage.blob",
            "google.cloud.storage", "confluent_kafka"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # SDK not installed in this build env
        print(f"[throughput.spec] skipping {pkg}: {exc}")

# Our own package, including the lazily-referenced tool/adapter modules.
hiddenimports += collect_submodules("throughput")

a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="throughput",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,          # CLI tool: prints the results table to the console
    disable_windowed_traceback=False,
)
