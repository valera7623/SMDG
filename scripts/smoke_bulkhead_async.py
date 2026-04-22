#!/usr/bin/env python3
"""Async smoke flood for Bulkhead-protected endpoints.

Examples:
  python scripts/smoke_bulkhead_async.py \
    --auth-header "Bearer <jwt>" \
    --upload-url "http://localhost:8000/api/upload" \
    --dicom-url "http://localhost:8000/api/dicom/render/123?token=<view_token>" \
    --export-url "http://localhost:8000/api/admin/audit/export?format=csv&start_date=2026-01-01&end_date=2026-01-31" \
    --concurrency 25 \
    --requests 100
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Coroutine

import aiohttp


@dataclass
class RequestResult:
    status: int
    latency_ms: float


def _build_headers(auth_header: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if auth_header:
        headers["Authorization"] = auth_header
    return headers


async def _do_upload(session: aiohttp.ClientSession, url: str, headers: dict[str, str]) -> RequestResult:
    started = time.perf_counter()
    payload = os.urandom(16 * 1024)
    form = aiohttp.FormData()
    form.add_field("file", payload, filename=f"smoke-{random.randint(1, 1_000_000)}.txt", content_type="text/plain")
    form.add_field("ttl_days", "1")
    form.add_field("max_downloads", "1")
    async with session.post(url, data=form, headers=headers) as response:
        _ = await response.read()
        return RequestResult(status=response.status, latency_ms=(time.perf_counter() - started) * 1000)


async def _do_get(session: aiohttp.ClientSession, url: str, headers: dict[str, str]) -> RequestResult:
    started = time.perf_counter()
    async with session.get(url, headers=headers) as response:
        _ = await response.read()
        return RequestResult(status=response.status, latency_ms=(time.perf_counter() - started) * 1000)


async def _run_flood(
    name: str,
    request_factory: Callable[[], Coroutine[None, None, RequestResult]],
    requests: int,
    concurrency: int,
) -> list[RequestResult]:
    semaphore = asyncio.Semaphore(concurrency)
    results: list[RequestResult] = []

    async def _worker() -> None:
        async with semaphore:
            results.append(await request_factory())

    await asyncio.gather(*(_worker() for _ in range(requests)))
    _print_summary(name, results)
    return results


def _print_summary(name: str, results: list[RequestResult]) -> None:
    status_counts = Counter(item.status for item in results)
    latencies = [item.latency_ms for item in results]
    p95 = statistics.quantiles(latencies, n=100)[94] if len(latencies) >= 2 else latencies[0]
    print(f"\n=== {name} ===")
    print(f"total={len(results)}")
    print(f"status_counts={dict(sorted(status_counts.items()))}")
    print(f"avg_ms={statistics.fmean(latencies):.1f} p95_ms={p95:.1f} max_ms={max(latencies):.1f}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Async bulkhead smoke flood")
    parser.add_argument("--auth-header", default=os.getenv("SMOKE_AUTH_HEADER"), help="Authorization header value")
    parser.add_argument("--upload-url", default=os.getenv("SMOKE_UPLOAD_URL"))
    parser.add_argument("--dicom-url", default=os.getenv("SMOKE_DICOM_URL"))
    parser.add_argument("--export-url", default=os.getenv("SMOKE_EXPORT_URL"))
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=25)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args()

    headers = _build_headers(args.auth_header)
    timeout = aiohttp.ClientTimeout(total=args.timeout_seconds)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        if args.upload_url:
            await _run_flood(
                "upload flood",
                lambda: _do_upload(session, args.upload_url, headers),
                requests=args.requests,
                concurrency=args.concurrency,
            )
        if args.dicom_url:
            await _run_flood(
                "dicom render flood",
                lambda: _do_get(session, args.dicom_url, headers),
                requests=args.requests,
                concurrency=args.concurrency,
            )
        if args.export_url:
            await _run_flood(
                "audit export flood",
                lambda: _do_get(session, args.export_url, headers),
                requests=args.requests,
                concurrency=max(2, min(args.concurrency, 10)),
            )


if __name__ == "__main__":
    asyncio.run(main())
