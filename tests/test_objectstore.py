import threading

from throughput.tools import objectstore


class FakeBlobStore:
    """In-memory object store standing in for any ObjectClient adapter."""

    def __init__(self):
        self.data = {}
        self.put_calls = 0
        self._lock = threading.Lock()

    def put(self, key, data):
        with self._lock:
            self.put_calls += 1
            self.data[key] = data

    def get(self, key):
        return self.data[key]

    def delete(self, key):
        self.data.pop(key, None)


SIZES = {"4KB": 4 * 1024, "1MB": 1024 * 1024}


def test_sweep_put_and_get_per_bucket():
    client = FakeBlobStore()
    rs = objectstore.run_object_sweep(client, "my-bucket", sizes=SIZES,
                                       total_payload_bytes=4 * 1024 * 1024,
                                       threads=4, tool="s3")
    ops = {(r.bucket, r.operation) for r in rs}
    assert ops == {("4KB", "put"), ("4KB", "get"),
                   ("1MB", "put"), ("1MB", "get")}
    assert all(r.tool == "s3" and r.target == "my-bucket" for r in rs)
    assert all(r.mb_per_s > 0 for r in rs)


def test_sweep_cleans_up_objects():
    client = FakeBlobStore()
    objectstore.run_object_sweep(client, "b", sizes={"4KB": 4 * 1024},
                                 total_payload_bytes=16 * 1024, threads=2)
    assert client.data == {}            # all deleted after each bucket


def test_multipart_flag_on_large_objects():
    client = FakeBlobStore()
    rs = objectstore.run_object_sweep(
        client, "b", sizes={"1KB": 1024, "16MB": 16 * 1024 * 1024},
        total_payload_bytes=16 * 1024 * 1024, threads=2, do_get=False)
    flags = {r.bucket: r.metadata["multipart_likely"] for r in rs}
    assert flags["1KB"] is False
    assert flags["16MB"] is True


def test_do_get_false_skips_reads():
    client = FakeBlobStore()
    rs = objectstore.run_object_sweep(client, "b", sizes={"4KB": 4 * 1024},
                                       total_payload_bytes=8 * 1024,
                                       do_get=False)
    assert all(r.operation == "put" for r in rs)


def test_s3_adapter_uses_injected_client():
    calls = []

    class FakeBody:
        def read(self): return b"x" * 10

    class FakeBoto:
        def put_object(self, **kw): calls.append(("put", kw["Key"]))
        def get_object(self, **kw):
            calls.append(("get", kw["Key"]))
            return {"Body": FakeBody()}
        def delete_object(self, **kw): calls.append(("del", kw["Key"]))

    a = objectstore.S3Adapter("bkt", client=FakeBoto())
    a.put("k", b"data")
    assert a.get("k") == b"x" * 10
    a.delete("k")
    assert [c[0] for c in calls] == ["put", "get", "del"]
