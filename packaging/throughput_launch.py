"""Frozen entry point for the Windows ``throughput.exe`` build.

PyInstaller needs a concrete script to freeze (not a ``module:func`` console
entry), so this just forwards to the real CLI. Keeping it tiny means the spec's
import analysis still starts from ``throughput.cli`` exactly as a normal run
would.
"""

import sys

from throughput.cli import main

if __name__ == "__main__":
    sys.exit(main())
