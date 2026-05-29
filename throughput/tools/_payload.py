"""Payload generation for the byte-moving benchmarks.

The size-sweep tools (filesweep, objectstore, mq) need a buffer of N bytes to
write/put/produce. Using ``os.urandom(N)`` for that draws the full N bytes from
the OS CSPRNG every bucket — needless CPU and entropy load on the host under
test, especially at the large end of the sweep (256 MB). The payload only needs
to resist compression and dedup on the *target* so throughput reflects real
bytes moved, not cryptographic strength.

``random_payload`` draws one small block of OS entropy and tiles it to the
requested size, mutating a few header bytes per tile so repeated blocks are not
byte-identical (defeats block-level dedup) while a compressor's window can't
reach across a full block (defeats compression). It returns a ``bytearray``
built in a single allocation, so peak memory stays at one times the payload
size — no transient copy.
"""

from __future__ import annotations

import os

# 1 MiB seed: larger than any common compression window (gzip/zlib is 32 KiB),
# small enough that the CSPRNG draw is negligible even for a 256 MB payload.
SEED_BLOCK = 1 << 20


def random_payload(size: int) -> bytearray:
    """A compression/dedup-resistant payload of ``size`` bytes.

    Cheaper than ``os.urandom(size)`` for large sizes: one ``SEED_BLOCK`` draw
    of OS entropy is tiled to ``size`` with a per-tile counter mixed into the
    leading bytes so successive blocks differ. Returns a ``bytearray`` (one
    allocation; safe to pass to ``write``/``put``/``produce``).
    """
    if size <= 0:
        return bytearray()
    if size <= SEED_BLOCK:
        return bytearray(os.urandom(size))
    seed = bytearray(os.urandom(SEED_BLOCK))
    buf = bytearray(size)
    counter = 0
    off = 0
    while off < size:
        n = SEED_BLOCK if size - off >= SEED_BLOCK else size - off
        # Vary the tile so block-level dedup on the target can't collapse it.
        seed[0] = counter & 0xFF
        seed[1] = (counter >> 8) & 0xFF
        seed[2] = (counter >> 16) & 0xFF
        buf[off:off + n] = seed[:n]
        off += n
        counter += 1
    return buf
