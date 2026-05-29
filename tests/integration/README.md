# Live integration test tier

These tests exercise the real backend adapters against actual services. They
are marked `@pytest.mark.integration` and **deselected by default** (see
`addopts = "-m 'not integration'"` in `pyproject.toml`), so a plain `pytest`
stays binary-/backend-free.

Run them explicitly once a backend is up:

```bash
pytest -m integration
```

Each test also skips itself unless its backend is configured via environment
variables, so `pytest -m integration` with nothing running is a no-op rather
than a failure.

## S3 (MinIO)

```bash
docker run -d -p 9000:9000 -e MINIO_ROOT_USER=minio \
  -e MINIO_ROOT_PASSWORD=minio123 minio/minio server /data

export THROUGHPUT_S3_ENDPOINT=http://127.0.0.1:9000
export THROUGHPUT_S3_BUCKET=throughput-test       # created if missing
export AWS_ACCESS_KEY_ID=minio
export AWS_SECRET_ACCESS_KEY=minio123
export AWS_DEFAULT_REGION=us-east-1

pip install -e .[s3]
pytest -m integration tests/integration/test_s3_minio.py
```

## Message queue (Kafka)

```bash
# any local broker, e.g. redpanda or kafka on localhost:9092
export THROUGHPUT_KAFKA_BOOTSTRAP=localhost:9092
export THROUGHPUT_KAFKA_TOPIC=throughput-test

pip install -e .[kafka]
pytest -m integration tests/integration/test_mq_kafka.py
```
