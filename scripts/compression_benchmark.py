#!/usr/bin/env python
"""Benchmark compression performance."""
from __future__ import annotations

import json
import time
from typing import Dict

import requests

BASE_URL = "http://localhost:8000"


def benchmark_compression(endpoint: str, data: Dict, iterations: int = 100):
    """Measure compression performance."""
    results = {
        "no_compression": {"times": [], "sizes": []},
        "gzip": {"times": [], "sizes": []},
        "brotli": {"times": [], "sizes": []},
    }

    for _ in range(iterations):
        start = time.time()
        response = requests.post(endpoint, json=data)
        elapsed = time.time() - start
        results["no_compression"]["times"].append(elapsed)
        results["no_compression"]["sizes"].append(len(response.content))

    for _ in range(iterations):
        start = time.time()
        response = requests.post(
            endpoint,
            json=data,
            headers={"Accept-Encoding": "gzip"},
        )
        elapsed = time.time() - start
        results["gzip"]["times"].append(elapsed)
        results["gzip"]["sizes"].append(len(response.content))

    for _ in range(iterations):
        start = time.time()
        response = requests.post(
            endpoint,
            json=data,
            headers={"Accept-Encoding": "br"},
        )
        elapsed = time.time() - start
        results["brotli"]["times"].append(elapsed)
        results["brotli"]["sizes"].append(len(response.content))

    return results


def print_results(results: Dict):
    """Print benchmark results."""
    print("\n" + "=" * 60)
    print("Compression Benchmark Results")
    print("=" * 60)

    for method, data in results.items():
        avg_time = sum(data["times"]) / len(data["times"]) * 1000
        avg_size = sum(data["sizes"]) / len(data["sizes"])

        print(f"\n{method.upper()}:")
        print(f"  Avg time: {avg_time:.2f}ms")
        print(f"  Avg size: {avg_size:.0f} bytes")

    no_comp_avg_size = sum(results["no_compression"]["sizes"]) / len(results["no_compression"]["sizes"])
    gzip_avg_size = sum(results["gzip"]["sizes"]) / len(results["gzip"]["sizes"])
    brotli_avg_size = sum(results["brotli"]["sizes"]) / len(results["brotli"]["sizes"])

    print("\nCompression Ratio:")
    print(f"  Gzip:   {(1 - gzip_avg_size / no_comp_avg_size) * 100:.1f}% reduction")
    print(f"  Brotli: {(1 - brotli_avg_size / no_comp_avg_size) * 100:.1f}% reduction")


if __name__ == "__main__":
    test_data = {
        "message": "x" * 10_000,
        "array": list(range(1000)),
        "nested": {"key": "value" * 100},
    }
    print(f"Testing compression on {len(json.dumps(test_data))} bytes payload")
    endpoint = f"{BASE_URL}/api/test/large-response"
    results = benchmark_compression(endpoint, test_data)
    print_results(results)
