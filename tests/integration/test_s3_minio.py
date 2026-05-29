"""Live S3 sweep against a real endpoint (MinIO in CI, or any S3).

Deselected by default (``integration`` marker) and self-skipping unless
``THROUGHPUT_S3_ENDPOINT`` + ``THROUGHPUT_S3_BUCKET`` are set, so it never runs
in a plain ``pytest``. See ``tests/integration/README.md`` for setup.
"""

import os

import pytest

from throughput.tools import objectstore

pytestmark = pytest.mark.integration

ENDPOINT = os.environ.get("THROUGHPUT_S3_ENDPOINT")
BUCKET = os.environ.get("THROUGHPUT_S3_BUCKET")


@pytest.fixture
def s3_client():
    if not ENDPOINT or not BUCKET:
        pytest.skip("set THROUGHPUT_S3_ENDPOINT and THROUGHPUT_S3_BUCKET")
    boto3 = pytest.importorskip("boto3")
    client = boto3.client("s3", endpoint_url=ENDPOINT)
    # Ensure the bucket exists (idempotent on MinIO).
    try:
        client.create_bucket(Bucket=BUCKET)
    except Exception:
        pass
    return client


def test_s3_put_get_sweep(s3_client):
    adapter = objectstore.S3Adapter(BUCKET, client=s3_client)
    rs = objectstore.run_object_sweep(
        adapter, BUCKET, sizes={"4KB": 4096, "1MB": 1024 * 1024},
        total_payload_bytes=4 * 1024 * 1024, threads=4, tool="s3")
    by_op = {(r.bucket, r.operation): r for r in rs}
    # both sizes, both ops, all actually moved bytes
    assert {("4KB", "put"), ("4KB", "get"),
            ("1MB", "put"), ("1MB", "get")} <= set(by_op)
    for r in rs:
        assert r.bytes_total > 0 and r.mb_per_s > 0
