"""Small helpers shared by binary-wrapping tools."""

from __future__ import annotations

import shutil
import subprocess


class ToolNotFound(RuntimeError):
    """Raised when a required external binary is not on PATH."""


def require(binary: str) -> str:
    path = shutil.which(binary)
    if not path:
        raise ToolNotFound(
            f"'{binary}' not found on PATH. Install it, or call the parser "
            f"directly with captured output for testing."
        )
    return path


def run_capture(cmd: list[str], timeout: float | None = None) -> str:
    """Run ``cmd`` and return stdout, raising on non-zero exit."""
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}"
        )
    return proc.stdout
