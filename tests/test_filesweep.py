from throughput.tools import filesweep


SIZES = {"4KB": 4 * 1024, "64KB": 64 * 1024}


def test_read_file_chunked_counts_full_size(tmp_path):
    # _read_file must report the whole file even when it spans many read chunks,
    # without ever holding the whole file in one buffer.
    path = tmp_path / "big.dat"
    nbytes = filesweep._READ_CHUNK * 2 + 777
    path.write_bytes(b"x" * nbytes)
    assert filesweep._read_file(path) == nbytes


def test_bucket_paths_shard_directories(tmp_path):
    ops = filesweep._FILES_PER_DIR * 2 + 5
    paths = filesweep._bucket_paths(tmp_path, ops)
    assert len(paths) == ops
    # No single directory holds more than the per-dir cap.
    per_dir = {}
    for p in paths:
        per_dir[p.parent] = per_dir.get(p.parent, 0) + 1
    assert max(per_dir.values()) <= filesweep._FILES_PER_DIR
    assert all(d.is_dir() for d in per_dir)        # dirs were pre-created


def test_sweep_writes_correct_bytes_to_disk(tmp_path):
    # End-to-end guard that the payload swap still moves the requested bytes.
    rs = filesweep.run_sweep(tmp_path, sizes={"4KB": 4 * 1024},
                             total_payload_bytes=40 * 1024, threads=4)
    write = next(r for r in rs if r.operation == "write")
    read = next(r for r in rs if r.operation == "read")
    assert write.bytes_total == 40 * 1024
    assert read.bytes_total == 40 * 1024           # chunked read saw every byte


def test_sweep_produces_read_and_write_per_bucket(tmp_path):
    rs = filesweep.run_sweep(tmp_path, sizes=SIZES,
                             total_payload_bytes=256 * 1024, threads=4)
    ops = {(r.bucket, r.operation) for r in rs}
    assert ops == {("4KB", "write"), ("4KB", "read"),
                   ("64KB", "write"), ("64KB", "read")}
    for r in rs:
        assert r.bytes_total == 256 * 1024     # constant payload per bucket
        assert r.mb_per_s > 0


def test_sweep_op_counts_match_payload(tmp_path):
    rs = filesweep.run_sweep(tmp_path, sizes={"4KB": 4 * 1024},
                             total_payload_bytes=40 * 1024, threads=2,
                             do_read=False)
    write = rs.results[0]
    assert write.ops == 10            # 40KB / 4KB
    assert write.operation == "write"


def test_sweep_cleans_up_temp_dir(tmp_path):
    filesweep.run_sweep(tmp_path, sizes={"4KB": 4 * 1024},
                        total_payload_bytes=8 * 1024, threads=1, do_read=False)
    # no leftover sweep_* directories
    assert not list(tmp_path.glob("sweep_*"))


def test_skip_read(tmp_path):
    rs = filesweep.run_sweep(tmp_path, sizes={"4KB": 4 * 1024},
                             total_payload_bytes=8 * 1024, do_read=False)
    assert all(r.operation == "write" for r in rs)


def test_run_nfs_labels_tool(tmp_path):
    rs = filesweep.run_nfs(tmp_path, sizes={"4KB": 4 * 1024},
                           total_payload_bytes=8 * 1024, do_read=False)
    assert all(r.tool == "nfs" for r in rs)
