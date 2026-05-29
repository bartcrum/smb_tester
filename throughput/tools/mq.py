"""Message-queue throughput — producer/consumer rates across message sizes.

Like the object-store tool, the engine is generic over a tiny client protocol
(``produce``/``consume``), so one sweep covers Kafka, RabbitMQ, SQS, etc. SDK
adapters are lazy-imported; an in-memory client makes the engine runnable and
tested here.
"""

from __future__ import annotations

import queue
import time
from typing import Protocol

from ..buckets import default_byte_sizes, ops_for_bucket
from ..results import BenchmarkResult, ResultSet, MB
from ._payload import random_payload


class MessageClient(Protocol):
    def produce(self, payload: bytes) -> None: ...
    def consume(self) -> bytes | None: ...


def run_mq_throughput(client: MessageClient, target: str, *,
                      sizes: dict[str, int] | None = None,
                      total_payload_bytes: int = 64 * MB,
                      do_consume: bool = True, tool: str = "mq") -> ResultSet:
    """Sweep produce/consume throughput across message sizes."""
    sizes = sizes or default_byte_sizes()
    rs = ResultSet()
    for label, size in sorted(sizes.items(), key=lambda kv: kv[1]):
        ops = ops_for_bucket(size, total_payload_bytes)
        payload = random_payload(size)

        start = time.perf_counter()
        for _ in range(ops):
            client.produce(payload)
        prod_s = max(time.perf_counter() - start, 1e-9)
        rs.add(BenchmarkResult(
            tool=tool, target=target, bucket=label, operation="produce",
            bytes_total=size * ops, ops=ops, seconds=prod_s, size_bytes=size,
        ))

        if do_consume:
            start = time.perf_counter()
            got = 0
            while got < ops:
                if client.consume() is None:
                    break
                got += 1
            cons_s = max(time.perf_counter() - start, 1e-9)
            rs.add(BenchmarkResult(
                tool=tool, target=target, bucket=label, operation="consume",
                bytes_total=size * got, ops=got, seconds=cons_s,
                size_bytes=size,
            ))
    return rs


class InMemoryQueueClient:
    """A real, usable client backed by ``queue.Queue`` — for local testing."""

    def __init__(self):
        self._q: queue.Queue[bytes] = queue.Queue()

    def produce(self, payload: bytes) -> None:
        self._q.put(payload)

    def consume(self) -> bytes | None:
        try:
            return self._q.get_nowait()
        except queue.Empty:
            return None


class KafkaAdapter:
    """confluent-kafka adapter (lazy import)."""

    def __init__(self, topic: str, *, bootstrap_servers: str = "localhost:9092",
                 producer=None, consumer=None):
        self.topic = topic
        if producer is not None:
            self._p = producer
        else:
            from confluent_kafka import Producer  # lazy
            self._p = Producer({"bootstrap.servers": bootstrap_servers})
        self._c = consumer

    def produce(self, payload: bytes) -> None:
        self._p.produce(self.topic, payload)
        self._p.poll(0)

    def consume(self) -> bytes | None:
        msg = self._c.poll(1.0)
        return msg.value() if msg and not msg.error() else None


class SQSAdapter:
    """boto3 SQS adapter (lazy import)."""

    def __init__(self, queue_url: str, *, client=None):
        self.queue_url = queue_url
        if client is not None:
            self._c = client
        else:
            import boto3  # lazy
            self._c = boto3.client("sqs")

    def produce(self, payload: bytes) -> None:
        self._c.send_message(QueueUrl=self.queue_url,
                             MessageBody=payload.decode("latin-1"))

    def consume(self) -> bytes | None:
        resp = self._c.receive_message(QueueUrl=self.queue_url,
                                       MaxNumberOfMessages=1)
        msgs = resp.get("Messages", [])
        if not msgs:
            return None
        self._c.delete_message(QueueUrl=self.queue_url,
                               ReceiptHandle=msgs[0]["ReceiptHandle"])
        return msgs[0]["Body"].encode("latin-1")
