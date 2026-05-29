"""Bounded-overhead parallel execution for the sweep tools.

The size sweeps fan a per-item function (write a file, PUT an object) across a
thread pool. Submitting one future *per item* makes the Python dispatch + GIL +
queue overhead dominate for small buckets — the 4 KB bucket of a 256 MB sweep
is 65 536 items, so the measured rate reflects the executor, not the target.

``map_chunked`` instead splits the work into at most ``threads`` contiguous
slices and hands each worker a whole slice to drain in a plain loop. That keeps
the same degree of concurrency while cutting submitted tasks from O(items) to
O(threads), so the harness's own overhead stops confounding small-bucket
numbers (and stops burning host CPU on task plumbing).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Sequence


def map_chunked(fn: Callable[[object], object], items: Sequence,
                threads: int) -> None:
    """Apply ``fn`` to every item across ``threads`` workers (chunked).

    Each of up to ``threads`` workers drains a contiguous slice, so the number
    of submitted tasks is O(threads) rather than O(len(items)). Results are
    discarded — callers use this for its side effects and time the wall clock.
    """
    n = len(items)
    if threads <= 1 or n <= 1:
        for it in items:
            fn(it)
        return

    k = min(threads, n)
    size = (n + k - 1) // k  # ceil, so we produce at most k chunks
    chunks = [items[i:i + size] for i in range(0, n, size)]

    def worker(chunk) -> None:
        for it in chunk:
            fn(it)

    with ThreadPoolExecutor(max_workers=len(chunks)) as ex:
        list(ex.map(worker, chunks))
