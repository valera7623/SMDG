# app/templating.py
"""Jinja2: шаблоны приложения и хелперы URL статики / CDN."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.config import settings

if TYPE_CHECKING:
    from jinja2 import Environment
    from fastapi.templating import Jinja2Templates

_TEMPLATES: Any = None


def _static_fallback_url(path: str) -> str:
    p = path.lstrip("/")
    base = settings.STATIC_URL.rstrip("/")
    return f"/{base}/{p}".replace("//", "/")


def _env_dir() -> str:
    return str(Path(__file__).resolve().parent / "templates")


def _apply_jinja_env_globals(environment: Any) -> None:
    from app.core.asset_pipeline import asset_pipeline

    def asset_url(path: str) -> str:
        if asset_pipeline and settings.ASSET_FINGERPRINTING:
            return asset_pipeline.get_asset_url(path)
        return _static_fallback_url(path)

    def css_url() -> str:
        if asset_pipeline and settings.ASSET_FINGERPRINTING:
            return asset_pipeline.get_css_url()
        return _static_fallback_url("css/style.css")

    def js_url(name: str = "main") -> str:
        if asset_pipeline and settings.ASSET_FINGERPRINTING:
            return asset_pipeline.get_js_url(name)
        return _static_fallback_url(f"js/{name}.js")

    environment.globals["asset_url"] = asset_url
    environment.globals["css_url"] = css_url
    environment.globals["js_url"] = js_url
    environment.globals["cdn_url"] = settings.CDN_URL if settings.CDN_ENABLED else ""
    environment.globals["static_url"] = settings.STATIC_URL
    environment.globals["asset_version"] = settings.STATIC_CACHE_VERSION
    environment.globals["api_url"] = settings.API_PUBLIC_URL
    environment.globals["asset_pipeline"] = asset_pipeline


def create_jinja_env(template_dir: str | None = None) -> "Environment":
    """Jinja2 Environment (скрипты, тесты) с теми же хелперами, что и HTTP-шаблоны."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    tdir = template_dir or _env_dir()
    env = Environment(
        loader=FileSystemLoader(tdir),
        autoescape=select_autoescape(["html", "xml"]),
    )
    _apply_jinja_env_globals(env)
    return env


def get_templates() -> "Jinja2Templates":
    from fastapi.templating import Jinja2Templates

    global _TEMPLATES
    if _TEMPLATES is None:
        _TEMPLATES = Jinja2Templates(directory=_env_dir())
    _apply_jinja_env_globals(_TEMPLATES.env)
    return _TEMPLATES


def update_jinja_globals() -> None:
    """Вызвать после init_asset_pipeline, чтобы Jinja2 увидел manifest."""
    get_templates()
