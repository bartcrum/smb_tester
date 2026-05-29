import zlib

from throughput.tools._payload import SEED_BLOCK, random_payload


def test_returns_exact_size_small_and_large():
    assert len(random_payload(0)) == 0
    assert len(random_payload(100)) == 100
    assert len(random_payload(SEED_BLOCK)) == SEED_BLOCK
    assert len(random_payload(SEED_BLOCK * 3 + 123)) == SEED_BLOCK * 3 + 123


def test_negative_size_is_empty():
    assert random_payload(-5) == bytearray()


def test_returns_bytes_like_writable_buffer():
    buf = random_payload(64)
    assert isinstance(buf, (bytes, bytearray))
    assert len(bytes(buf)) == 64           # convertible / usable as bytes


def test_tiles_are_not_byte_identical():
    # Two successive seed-block tiles must differ (defeats block-level dedup).
    buf = random_payload(SEED_BLOCK * 2)
    first = bytes(buf[:16])
    second = bytes(buf[SEED_BLOCK:SEED_BLOCK + 16])
    assert first != second


def test_resists_compression():
    # A tiled payload should stay essentially incompressible: the seed block is
    # larger than zlib's 32 KiB window, so repeats can't be collapsed.
    buf = bytes(random_payload(SEED_BLOCK * 4))
    ratio = len(zlib.compress(buf)) / len(buf)
    assert ratio > 0.95
