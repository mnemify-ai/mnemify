"""Unit tests for NotionClient — rate limiter behavior."""

from __future__ import annotations

import asyncio
import time

from src.harvester.notion.client import NotionClient


def _make_client(rate_limit: float = 3.0, rate_buffer: float = 0.5) -> NotionClient:
    return NotionClient(token="test", rate_limit=rate_limit, rate_buffer=rate_buffer)


async def test_burst_within_capacity_passes_immediately():
    client = _make_client()  # capacity = round(1.5) = 2
    try:
        start = time.monotonic()
        await client._wait_for_rate_limit()
        await client._wait_for_rate_limit()
        elapsed = time.monotonic() - start
        assert elapsed < 0.05, f"Burst of 2 should be instant, took {elapsed:.3f}s"
    finally:
        await client.close()


async def test_third_request_waits_for_window_to_age_out():
    client = _make_client()  # capacity = 2
    try:
        await client._wait_for_rate_limit()
        await client._wait_for_rate_limit()
        start = time.monotonic()
        await client._wait_for_rate_limit()
        elapsed = time.monotonic() - start
        assert 0.9 <= elapsed <= 1.2, (
            f"Third request should wait ~1s for window roll, took {elapsed:.3f}s"
        )
    finally:
        await client.close()


async def test_concurrent_tasks_share_budget_and_do_not_serialize():
    """10 concurrent requests at capacity=2 should finish in ~4-5s, not ~10s."""
    client = _make_client()
    try:
        start = time.monotonic()
        await asyncio.gather(*(client._wait_for_rate_limit() for _ in range(10)))
        elapsed = time.monotonic() - start
        assert elapsed < 6.0, (
            f"10 concurrent admits at cap=2/sec should finish under 6s, took {elapsed:.3f}s"
        )
        assert elapsed >= 3.5, (
            f"10 admits at cap=2/sec cannot physically complete in <3.5s, got {elapsed:.3f}s"
        )
    finally:
        await client.close()


async def test_capacity_floor_is_one():
    """Tiny effective rate rounds up to at least capacity 1."""
    client = _make_client(rate_limit=1.0, rate_buffer=0.9)  # 0.1 → round=0 → floor 1
    try:
        assert client._rate_capacity >= 1
        await client._wait_for_rate_limit()  # must not hang
    finally:
        await client.close()
