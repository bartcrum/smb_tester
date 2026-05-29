"""throughput — a benchmarking suite for file and network services.

Every tool emits the same :class:`~throughput.results.BenchmarkResult` shape so
results are directly comparable across protocols (SMB, NFS, S3, HTTP, ...), and
the shared CSV/JSON exporters and baseline-diff logic work everywhere.
"""

from .results import BenchmarkResult, ResultSet, MB
from .buckets import default_byte_sizes, sweep_buckets
from .prometheus import render_prometheus, write_prometheus

__all__ = [
    "BenchmarkResult",
    "ResultSet",
    "MB",
    "default_byte_sizes",
    "sweep_buckets",
    "render_prometheus",
    "write_prometheus",
]

__version__ = "0.2.0"
