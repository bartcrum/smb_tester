import pytest

from throughput.buckets import default_byte_sizes, ops_for_bucket, sweep_buckets, MB


def test_default_sizes_are_sorted_range():
    sizes = default_byte_sizes()
    assert sizes["4KB"] == 4 * 1024
    assert sizes["256MB"] == 256 * MB
    # returns a fresh copy each call
    sizes["bogus"] = 1
    assert "bogus" not in default_byte_sizes()


def test_ops_for_bucket_constant_payload():
    total = 2048 * MB
    assert ops_for_bucket(1 * MB, total) == 2048
    assert ops_for_bucket(256 * MB, total) == 8
    # tiny files relative to payload -> many ops
    assert ops_for_bucket(4 * 1024, total) == total // (4 * 1024)


def test_ops_for_bucket_floor_at_one():
    # a single file bigger than the whole payload still runs once
    assert ops_for_bucket(10 * MB, 1 * MB) == 1


def test_ops_for_bucket_rejects_nonpositive():
    with pytest.raises(ValueError):
        ops_for_bucket(0, 100)


def test_sweep_runs_smallest_first_with_op_counts():
    seen = []
    sizes = {"1MB": MB, "4KB": 4 * 1024, "16MB": 16 * MB}
    list(sweep_buckets(sizes, total_payload_bytes=16 * MB,
                       run_bucket=lambda label, size, ops: seen.append((label, size, ops))))
    labels = [s[0] for s in seen]
    assert labels == ["4KB", "1MB", "16MB"]      # ascending by size
    assert seen[-1] == ("16MB", 16 * MB, 1)      # 16MB payload / 16MB file = 1 op
