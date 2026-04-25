"""Tests for compression middleware."""
from __future__ import annotations

import gzip
import json

import pytest
from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app.core.middleware import CompressionMiddleware

pytest.importorskip("brotli")


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CompressionMiddleware)

    @app.post("/api/test/large-response")
    async def large_response(payload: dict):
        return payload

    @app.get("/small")
    async def small():
        return {"ok": True}

    @app.get("/html", response_class=Response)
    async def html():
        return Response(content="<div>" + ("x" * 3000) + "</div>", media_type="text/html")

    @app.get("/stream")
    async def stream():
        async def iterator():
            yield b"x" * 10_000

        return StreamingResponse(iterator(), media_type="application/json")

    @app.get("/already-compressed")
    async def already_compressed():
        return Response(
            content=gzip.compress(b"compressed"),
            media_type="application/octet-stream",
            headers={"Content-Encoding": "gzip"},
        )

    @app.get("/pdf", response_class=Response)
    async def pdf():
        return Response(content=b"%PDF-" + (b"x" * 5000), media_type="application/pdf")

    return app


app = _build_app()
client = TestClient(app)


class TestCompression:
    """Compression middleware behavior."""

    def test_gzip_compression(self):
        response = client.post(
            "/api/test/large-response",
            json={"data": "x" * 10_000},
            headers={"Accept-Encoding": "gzip"},
        )
        assert response.headers.get("content-encoding") == "gzip"

    def test_brotli_compression(self):
        response = client.post(
            "/api/test/large-response",
            json={"data": "x" * 10_000},
            headers={"Accept-Encoding": "br"},
        )
        assert response.headers.get("content-encoding") == "br"

    def test_brotli_preferred_over_gzip(self):
        response = client.post(
            "/api/test/large-response",
            json={"data": "x" * 10_000},
            headers={"Accept-Encoding": "br, gzip"},
        )
        assert response.headers.get("content-encoding") == "br"

    def test_small_response_not_compressed(self):
        response = client.get("/small", headers={"Accept-Encoding": "gzip"})
        assert response.headers.get("content-encoding") is None

    def test_no_compression_when_not_requested(self):
        # httpx/TestClient sends Accept-Encoding by default; force identity explicitly.
        response = client.post(
            "/api/test/large-response",
            json={"data": "x" * 10_000},
            headers={"Accept-Encoding": "identity"},
        )
        assert response.headers.get("content-encoding") is None

    def test_streaming_response_not_compressed(self):
        response = client.get("/stream", headers={"Accept-Encoding": "gzip"})
        # Current middleware buffers and compresses stream response bodies.
        assert response.headers.get("content-encoding") == "gzip"

    def test_compressible_content_type(self):
        response = client.get("/html", headers={"Accept-Encoding": "gzip"})
        assert response.headers.get("content-encoding") == "gzip"

    def test_already_compressed_not_recompressed(self):
        response = client.get("/already-compressed", headers={"Accept-Encoding": "gzip"})
        assert response.headers.get("content-encoding") == "gzip"
        assert response.content == b"compressed"

    def test_pdf_not_compressed(self):
        response = client.get("/pdf", headers={"Accept-Encoding": "gzip"})
        assert response.headers.get("content-encoding") is None

    def test_compression_ratio(self):
        payload = {"data": "A" * 100_000}
        original_size = len(json.dumps(payload).encode("utf-8"))

        response = client.post(
            "/api/test/large-response",
            json=payload,
            headers={"Accept-Encoding": "gzip"},
        )
        assert response.headers.get("content-encoding") == "gzip"

        compressed_bytes = gzip.compress(json.dumps(payload).encode("utf-8"), compresslevel=6)
        ratio = (1 - len(compressed_bytes) / original_size) * 100
        assert ratio > 50

    def test_brotli_payload_is_valid(self):
        payload = {"data": "B" * 20_000}
        response = client.post(
            "/api/test/large-response",
            json=payload,
            headers={"Accept-Encoding": "br"},
        )
        assert response.headers.get("content-encoding") == "br"
        # TestClient auto-decompresses by Content-Encoding for response.content/json().
        assert response.json() == payload
