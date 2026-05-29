"""Object-store throughput benchmark (S3, Azure Blob, GCS).

Same small-vs-large curve as the file tools, but for object stores — it
surfaces per-object request overhead (tiny objects are request-bound) and where
multipart/chunked thresholds kick in.

The sweep is generic over a tiny ``ObjectClient`` protocol (``put``/``get``/
``delete``), so one engine covers every backend; the SDK-specific adapters
(boto3, azure-storage-blob, google-cloud-storage) are lazy-imported so the
suite imports fine without them installed, and the engine is testable with an
in-memory fake.
"""

from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from ..buckets import default_byte_sizes, ops_for_bucket
from ..results import BenchmarkResult, ResultSet, MB


class ObjectClient(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


def _timed(fn, items, threads: int) -> float:
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, threads)) as ex:
        list(ex.map(fn, items))
    return max(time.perf_counter() - start, 1e-9)


def run_object_sweep(client: ObjectClient, container: str, *,
                     sizes: dict[str, int] | None = None,
                     total_payload_bytes: int = 256 * MB, threads: int = 16,
                     do_get: bool = True, tool: str = "s3",
                     prefix: str | None = None) -> ResultSet:
    """Parallel PUT/GET sweep across object sizes against ``container``."""
    sizes = sizes or default_byte_sizes()
    prefix = prefix or f"sweep-{uuid.uuid4().hex[:8]}"
    rs = ResultSet()
    for label, size in sorted(sizes.items(), key=lambda kv: kv[1]):
        ops = ops_for_bucket(size, total_payload_bytes)
        data = os.urandom(size)
        keys = [f"{prefix}/{label}/obj_{i}" for i in range(ops)]

        put_s = _timed(lambda k: client.put(k, data), keys, threads)
        rs.add(BenchmarkResult(
            tool=tool, target=container, bucket=label, operation="put",
            bytes_total=size * ops, ops=ops, seconds=put_s, size_bytes=size,
            metadata={"threads": threads, "multipart_likely": size >= 8 * MB},
        ))

        if do_get:
            get_s = _timed(client.get, keys, threads)
            rs.add(BenchmarkResult(
                tool=tool, target=container, bucket=label, operation="get",
                bytes_total=size * ops, ops=ops, seconds=get_s,
                size_bytes=size, metadata={"threads": threads},
            ))

        for k in keys:
            try:
                client.delete(k)
            except Exception:
                pass
    return rs


# --------------------------------------------------------------------- adapters
class S3Adapter:
    """boto3-backed adapter. Lazy-imports boto3."""

    def __init__(self, bucket: str, *, endpoint_url: str | None = None,
                 region: str | None = None, client=None):
        self.bucket = bucket
        if client is not None:
            self._c = client
        else:
            import boto3  # lazy
            self._c = boto3.client("s3", endpoint_url=endpoint_url,
                                   region_name=region)

    def put(self, key: str, data: bytes) -> None:
        self._c.put_object(Bucket=self.bucket, Key=key, Body=data)

    def get(self, key: str) -> bytes:
        return self._c.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self._c.delete_object(Bucket=self.bucket, Key=key)


class AzureBlobAdapter:
    """azure-storage-blob adapter. Lazy-imports the SDK."""

    def __init__(self, container: str, *, connection_string: str | None = None,
                 container_client=None):
        if container_client is not None:
            self._cc = container_client
        else:
            from azure.storage.blob import BlobServiceClient  # lazy
            svc = BlobServiceClient.from_connection_string(connection_string)
            self._cc = svc.get_container_client(container)

    def put(self, key: str, data: bytes) -> None:
        self._cc.upload_blob(name=key, data=data, overwrite=True)

    def get(self, key: str) -> bytes:
        return self._cc.download_blob(key).readall()

    def delete(self, key: str) -> None:
        self._cc.delete_blob(key)


class GCSAdapter:
    """google-cloud-storage adapter. Lazy-imports the SDK."""

    def __init__(self, bucket: str, *, bucket_obj=None):
        if bucket_obj is not None:
            self._b = bucket_obj
        else:
            from google.cloud import storage  # lazy
            self._b = storage.Client().bucket(bucket)

    def put(self, key: str, data: bytes) -> None:
        self._b.blob(key).upload_from_string(data)

    def get(self, key: str) -> bytes:
        return self._b.blob(key).download_as_bytes()

    def delete(self, key: str) -> None:
        self._b.blob(key).delete()


def run_s3(bucket: str, **sweep_kw) -> ResultSet:
    adapter_kw = {k: sweep_kw.pop(k) for k in ("endpoint_url", "region")
                  if k in sweep_kw}
    return run_object_sweep(S3Adapter(bucket, **adapter_kw), bucket,
                            tool="s3", **sweep_kw)
