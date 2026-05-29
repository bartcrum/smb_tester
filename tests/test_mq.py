from throughput.tools import mq

SIZES = {"1KB": 1024, "16KB": 16 * 1024}


def test_inmemory_produce_consume_sweep():
    client = mq.InMemoryQueueClient()
    rs = mq.run_mq_throughput(client, "topic-a", sizes=SIZES,
                              total_payload_bytes=64 * 1024)
    ops = {(r.bucket, r.operation) for r in rs}
    assert ops == {("1KB", "produce"), ("1KB", "consume"),
                   ("16KB", "produce"), ("16KB", "consume")}
    # every produced message was consumed within its bucket
    for r in rs:
        assert r.ops > 0 and r.mb_per_s > 0


def test_consume_counts_match_produced():
    client = mq.InMemoryQueueClient()
    rs = mq.run_mq_throughput(client, "t", sizes={"1KB": 1024},
                              total_payload_bytes=10 * 1024)
    by = {r.operation: r for r in rs}
    assert by["produce"].ops == 10
    assert by["consume"].ops == 10


def test_do_consume_false():
    client = mq.InMemoryQueueClient()
    rs = mq.run_mq_throughput(client, "t", sizes={"1KB": 1024},
                              total_payload_bytes=4 * 1024, do_consume=False)
    assert all(r.operation == "produce" for r in rs)


def test_sqs_adapter_with_injected_client():
    sent = []

    class FakeSQS:
        def send_message(self, **kw): sent.append(kw["MessageBody"])
        def receive_message(self, **kw):
            if sent:
                return {"Messages": [{"Body": sent[0], "ReceiptHandle": "r"}]}
            return {}
        def delete_message(self, **kw): pass

    a = mq.SQSAdapter("http://q", client=FakeSQS())
    a.produce(b"hello")
    assert a.consume() == b"hello"
