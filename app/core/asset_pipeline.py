# app/core/asset_pipeline.py
"""Asset pipeline with fingerprinting for CDN cache busting."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Уже с fingerprint: name.<12 hex>.ext
_FINGERPRINTED = re.compile(r"^(.+)\.([a-f0-9]{12})(\.[^.]+)$")


class AssetPipeline:
    """Сопоставление логических путей статики с версионированными именами (CDN / cache-bust)."""

    def __init__(
        self,
        static_dir: Path,
        static_url: str,
        cdn_url: Optional[str] = None,
        *,
        auto_generate: bool = False,
        fingerprinting: bool = True,
    ) -> None:
        self.static_dir = static_dir.resolve()
        su = static_url.strip()
        if not su.startswith("/"):
            su = "/" + su
        if not su.endswith("/"):
            su += "/"
        self.static_url = su
        self.cdn_url = cdn_url.rstrip("/") if cdn_url else None
        self.fingerprinting = fingerprinting
        self.manifest: Dict[str, str] = {}
        self.manifest_file = self.static_dir / "manifest.json"

        if self.manifest_file.exists():
            self.load_manifest()
        elif auto_generate and self.fingerprinting:
            self.generate_manifest()
        else:
            logger.info(
                "Asset manifest not found at %s (passthrough URLs until generated)",
                self.manifest_file,
            )

    @staticmethod
    def _fingerprint_file(content: bytes) -> str:
        return hashlib.md5(content, usedforsecurity=False).hexdigest()[:12]

    @classmethod
    def _is_fingerprinted_name(cls, path: Path) -> bool:
        if path.name == "manifest.json":
            return True
        m = _FINGERPRINTED.match(path.name)
        return m is not None

    def generate_manifest(self) -> None:
        """Собирает manifest.json и копии файлов с хэшем в имени (для выкладки в S3/CDN)."""
        self.manifest = {}

        for file_path in self.static_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if self._is_fingerprinted_name(file_path):
                continue

            try:
                relative = file_path.relative_to(self.static_dir)
            except ValueError:
                continue
            rel_s = str(relative).replace("\\", "/")
            if rel_s == "manifest.json":
                continue

            ext = file_path.suffix.lower()
            content = file_path.read_bytes()
            fp = self._fingerprint_file(content)
            stem = file_path.stem
            versioned_name = f"{stem}.{fp}{ext}"
            versioned_path = file_path.parent / versioned_name

            if versioned_path.resolve() != file_path.resolve():
                shutil.copy2(file_path, versioned_path)

            self.manifest[rel_s] = str(versioned_path.relative_to(self.static_dir)).replace(
                "\\", "/"
            )

        self.save_manifest()
        logger.info("Generated asset manifest with %d entries", len(self.manifest))

    def save_manifest(self) -> None:
        with open(self.manifest_file, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2, sort_keys=True)

    def load_manifest(self) -> None:
        with open(self.manifest_file, "r", encoding="utf-8") as f:
            data: Any = json.load(f)
        if isinstance(data, dict):
            # Нормализуем к plain str -> str (без query-ключей из старых форматов)
            self.manifest = {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
        else:
            self.manifest = {}
        logger.info("Loaded asset manifest with %d entries from %s", len(self.manifest), self.manifest_file)

    def _normalize(self, asset_path: str) -> str:
        return str(Path(asset_path)).replace("\\", "/").lstrip("/")

    def _join_url(self, relative_versioned: str) -> str:
        relative_versioned = relative_versioned.lstrip("/")
        path = f"{self.static_url}{relative_versioned}"
        if self.cdn_url:
            return f"{self.cdn_url.rstrip('/')}{path}"
        return path

    def get_asset_url(self, asset_path: str) -> str:
        if not self.fingerprinting:
            return self._join_url(self._normalize(asset_path))

        rel = self._normalize(asset_path)
        versioned = self.manifest.get(rel, rel)
        return self._join_url(versioned)

    def get_css_url(self) -> str:
        return self.get_asset_url("css/style.css")

    def get_language_selector_css_url(self) -> str:
        return self.get_asset_url("css/language-selector.css")

    def get_js_url(self, name: str = "main") -> str:
        n = name.strip("/").removesuffix(".js")
        return self.get_asset_url(f"js/{n}.js")

    def get_dicom_viewer_url(self) -> str:
        return self.get_asset_url("html/dicom-viewer.html")

    def get_image_url(self, image_name: str) -> str:
        return self.get_asset_url(f"img/{image_name}")

    def get_favicon_url(self) -> str:
        return self.get_asset_url("favicon.ico")


asset_pipeline: Optional[AssetPipeline] = None


def init_asset_pipeline(
    static_dir: Path,
    static_url: str,
    cdn_url: Optional[str] = None,
    *,
    auto_generate: bool = False,
    fingerprinting: bool = True,
) -> AssetPipeline:
    global asset_pipeline
    asset_pipeline = AssetPipeline(
        static_dir,
        static_url,
        cdn_url,
        auto_generate=auto_generate,
        fingerprinting=fingerprinting,
    )
    return asset_pipeline
