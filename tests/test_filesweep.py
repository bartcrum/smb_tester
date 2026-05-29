from throughput.tools import filesweep


SIZES = {"4KB": 4 * 1024, "64KB": 64 * 1024}


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
