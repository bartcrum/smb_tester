import threading

from throughput.tools._parallel import map_chunked


def test_every_item_processed_exactly_once():
    seen = []
    lock = threading.Lock()

    def record(x):
        with lock:
            seen.append(x)

    items = list(range(1000))
    map_chunked(record, items, threads=8)
    assert sorted(seen) == items          # all, no dupes, no drops


def test_single_thread_path():
    seen = []
    map_chunked(seen.append, [1, 2, 3], threads=1)
    assert seen == [1, 2, 3]


def test_more_threads_than_items():
    seen = []
    lock = threading.Lock()
    map_chunked(lambda x: (lock.acquire(), seen.append(x), lock.release()),
                [1, 2], threads=16)
    assert sorted(seen) == [1, 2]


def test_empty_items_is_noop():
    map_chunked(lambda x: 1 / 0, [], threads=4)   # never called → no error


def test_concurrency_bounded_by_threads():
    # The whole point: at most `threads` workers run, so task count is O(threads)
    # not O(items). Distinct worker thread ids must not exceed the thread cap.
    ids = set()
    lock = threading.Lock()

    def record(_):
        with lock:
            ids.add(threading.get_ident())

    map_chunked(record, list(range(5000)), threads=4)
    assert 1 <= len(ids) <= 4
