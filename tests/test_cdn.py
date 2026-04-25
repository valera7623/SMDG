"""Тесты CDN / asset pipeline (без обязательной БД)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.asset_pipeline import AssetPipeline
from app.core.config import settings


def test_cdn_url_generation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "CDN_ENABLED", True)
    monkeypatch.setattr(settings, "CDN_URL", "https://cdn.example.com")
    monkeypatch.setattr(settings, "ASSET_FINGERPRINTING", True)

    (tmp_path / "css").mkdir()
    (tmp_path / "css" / "style.css").write_text("body{}", encoding="utf-8")

    pipeline = AssetPipeline(
        tmp_path,
        "/static/",
        cdn_url="https://cdn.example.com",
        auto_generate=True,
        fingerprinting=True,
    )
    css_url = pipeline.get_css_url()
    assert css_url.startswith("https://cdn.example.com/static/")
    assert ".css" in css_url
    assert "css/style." in css_url or "style." in css_url


def test_asset_fingerprint(tmp_path: Path) -> None:
    (tmp_path / "css").mkdir()
    (tmp_path / "css" / "style.css").write_text("x { color: red; }", encoding="utf-8")

    pipeline = AssetPipeline(
        tmp_path,
        "/static/",
        cdn_url=None,
        auto_generate=True,
        fingerprinting=True,
    )
    css_url = pipeline.get_css_url()
    assert "/static/" in css_url
    assert "?" not in css_url
    last = css_url.rstrip("/").split("/")[-1]
    assert "." in last


def test_manifest_generation(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "test.css").write_text("body { color: red; }", encoding="utf-8")

    AssetPipeline(
        static_dir,
        "/static/",
        cdn_url=None,
        auto_generate=True,
        fingerprinting=True,
    )
    manifest_file = static_dir / "manifest.json"
    assert manifest_file.exists()
    import json

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert "test.css" in manifest


def test_static_file_served() -> None:
    from app.main import app

    with TestClient(app) as client:
        r = client.get("/static/css/style.css")
    assert r.status_code == 200
    assert "text/css" in r.headers.get("content-type", "") or r.content


def test_index_uses_template(monkeypatch) -> None:
    from app.main import app

    monkeypatch.setattr(settings, "CDN_ENABLED", False)
    with TestClient(app) as client:
        r = client.get("/")
    assert r.status_code == 200
    assert b"SMDG" in r.content or b"Secure" in r.content
