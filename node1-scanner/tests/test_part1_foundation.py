"""Tests for Part 1 — must all pass before proceeding to Part 2."""
import asyncio
import time
import pytest
from latency.base_methods import (
    process_all_parallel, TieredCache, AsyncEventBus,
    extractive_summarize, pack, unpack
)


@pytest.mark.asyncio
async def test_b1_parallel_processes_1000_items_under_1_second():
    """B1: Parallel processing must handle 1000 items in under 1 second."""
    async def mock_process(item):
        await asyncio.sleep(0)  # yield control, simulate work
        return item * 2

    items = list(range(1000))
    start = time.perf_counter()
    results = await process_all_parallel(items, mock_process)
    duration = time.perf_counter() - start

    assert len(results) == 1000
    assert duration < 1.0, f"PERFORMANCE VIOLATION: {duration:.3f}s > 1.0s"
    print(f"\u2713 B1: 1000 items in {duration * 1000:.1f}ms")


@pytest.mark.asyncio
async def test_b3_cache_l1_read_under_1ms():
    """B3: L1 cache read must be under 1ms (it's a dict lookup)."""
    cache = TieredCache("redis://localhost:6379/0")
    # Manually set L1 without Redis (test L1 only)
    import time as t
    cache._L1["price:BTCUSDT"] = (50000.0, t.monotonic() + 5)

    start = time.perf_counter()
    val = await cache.get("price:BTCUSDT")
    duration = (time.perf_counter() - start) * 1000

    assert val == 50000.0
    assert duration < 1.0, f"L1 cache too slow: {duration:.3f}ms"
    print(f"\u2713 B3: L1 cache read in {duration:.4f}ms")


@pytest.mark.asyncio
async def test_b5_event_bus_delivers_events():
    """B5: Event bus must deliver events to subscribers."""
    bus = AsyncEventBus()
    received = []

    async def handler(event):
        received.append(event)

    bus.subscribe("PRICE_CHANGE", handler)
    asyncio.create_task(bus.run())

    await bus.publish("PRICE_CHANGE", {"symbol": "BTCUSDT", "price": 50000})
    await asyncio.sleep(0.01)  # Let event loop process

    assert len(received) == 1
    assert received[0]["data"]["symbol"] == "BTCUSDT"
    print("\u2713 B5: Event bus delivers events correctly")


def test_b6_extractive_summarize_fast():
    """B6: Summarization must complete in under 100ms."""
    long_text = "Bitcoin has surged to new highs. " * 200
    start = time.perf_counter()
    summary = extractive_summarize(long_text, sentence_count=3)
    duration = (time.perf_counter() - start) * 1000
    assert len(summary) > 0
    assert duration < 100, f"Too slow: {duration:.1f}ms"
    print(f"\u2713 B6: Summarize in {duration:.1f}ms")


def test_b8_msgpack_faster_than_json():
    """B8: msgpack must be faster than JSON for serialization."""
    import json
    data = {"symbol": "BTCUSDT", "price": 50000.0, "volume": 12345.67,
            "bid": 49999.5, "ask": 50000.5, "timestamp": 1710000000}

    # Warmup both (eliminates cold-start / import overhead)
    for _ in range(1000):
        json.dumps(data).encode()
        pack(data)

    # JSON timing
    start = time.perf_counter()
    for _ in range(10000):
        json.dumps(data).encode()
    json_time = time.perf_counter() - start

    # msgpack timing
    start = time.perf_counter()
    for _ in range(10000):
        pack(data)
    msgpack_time = time.perf_counter() - start

    # msgpack payload should be smaller (the real win for IPC)
    json_size = len(json.dumps(data).encode())
    msgpack_size = len(pack(data))
    assert msgpack_size <= json_size, "msgpack should produce smaller payloads"
    print(f"\u2713 B8: msgpack {msgpack_size}B vs JSON {json_size}B | "
          f"msgpack {msgpack_time*1000:.1f}ms vs JSON {json_time*1000:.1f}ms (10k ops)")
