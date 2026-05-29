"""Live message-queue sweep against a real Kafka broker.

Deselected by default (``integration`` marker) and self-skipping unless
``THROUGHPUT_KAFKA_BOOTSTRAP`` is set. See ``tests/integration/README.md``.
"""

import os
import uuid

import pytest

from throughput.tools import mq

pytestmark = pytest.mark.integration

BOOTSTRAP = os.environ.get("THROUGHPUT_KAFKA_BOOTSTRAP")
TOPIC = os.environ.get("THROUGHPUT_KAFKA_TOPIC", "throughput-test")


@pytest.fixture
def kafka_client():
    if not BOOTSTRAP:
        pytest.skip("set THROUGHPUT_KAFKA_BOOTSTRAP to a reachable broker")
    confluent = pytest.importorskip("confluent_kafka")
    group = f"throughput-it-{uuid.uuid4().hex[:8]}"
    consumer = confluent.Consumer({
        "bootstrap.servers": BOOTSTRAP, "group.id": group,
        "auto.offset.reset": "earliest",
    })
    consumer.subscribe([TOPIC])
    client = mq.KafkaAdapter(TOPIC, bootstrap_servers=BOOTSTRAP,
                             consumer=consumer)
    yield client
    consumer.close()


def test_kafka_produce_consume_sweep(kafka_client):
    rs = mq.run_mq_throughput(
        kafka_client, TOPIC, sizes={"1KB": 1024},
        total_payload_bytes=64 * 1024, do_consume=True, tool="kafka")
    produce = [r for r in rs if r.operation == "produce"]
    assert produce and produce[0].bytes_total > 0 and produce[0].mb_per_s > 0
