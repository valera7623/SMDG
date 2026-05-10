"""Локализованные OpenAPI-схемы и Swagger UI."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse

from app.core.version import APP_VERSION

_OPENAPI_LOCALES: dict[str, dict[str, str]] = {
    "ru": {
        "title": "SMDG API (Русская документация)",
        "description": (
            "API для безопасного обмена медицинскими файлами.\n\n"
            "Возможности:\n"
            "- Сквозное шифрование (age)\n"
            "- Временные одноразовые ссылки\n"
            "- Двухфакторная аутентификация (TOTP)\n"
            "- Полный аудит действий\n"
            "- DICOM Viewer с измерениями\n"
            "- Экспорт аудита в Excel/PDF/CSV"
        ),
    },
    "de": {
        "title": "SMDG API (Deutsche Dokumentation)",
        "description": (
            "API für den sicheren Austausch medizinischer Dateien.\n\n"
            "Funktionen:\n"
            "- Ende-zu-Ende-Verschlüsselung (age)\n"
            "- Temporäre Einmal-Links\n"
            "- Zwei-Faktor-Authentifizierung (TOTP)\n"
            "- Vollständiges Audit aller Aktionen\n"
            "- DICOM-Viewer mit Messungen\n"
            "- Audit-Export in Excel/PDF/CSV"
        ),
    },
    "fr": {
        "title": "SMDG API (Documentation française)",
        "description": (
            "API pour l'échange sécurisé de fichiers médicaux.\n\n"
            "Fonctionnalités :\n"
            "- Chiffrement de bout en bout (age)\n"
            "- Liens temporaires à usage unique\n"
            "- Authentification à deux facteurs (TOTP)\n"
            "- Audit complet des actions\n"
            "- Visualiseur DICOM avec mesures\n"
            "- Export d'audit en Excel/PDF/CSV"
        ),
    },
}


def build_localised_openapi(app: FastAPI, lang: str) -> dict:
    """Return the OpenAPI schema with localised ``info`` metadata."""
    meta = _OPENAPI_LOCALES[lang]
    schema = get_openapi(
        title=meta["title"],
        version=APP_VERSION,
        description=meta["description"],
        routes=app.routes,
    )
    schema.setdefault("info", {})["x-language"] = lang
    return schema


def swagger_ui_html(openapi_url: str, title: str) -> HTMLResponse:
    """Render a minimal Swagger UI shell pointing at ``openapi_url``."""
    html = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"UTF-8\">
    <title>{title}</title>
    <link rel=\"stylesheet\" href=\"https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css\">
</head>
<body>
    <div id=\"swagger-ui\"></div>
    <script src=\"https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js\"></script>
    <script>
        window.ui = SwaggerUIBundle({{
            url: '{openapi_url}',
            dom_id: '#swagger-ui',
            deepLinking: true,
        }});
    </script>
</body>
</html>"""
    return HTMLResponse(html)


def register_localized_openapi_routes(app: FastAPI) -> None:
    """Регистрирует /openapi.{lang}.json и /docs/{lang}."""

    @app.get("/openapi.ru.json", include_in_schema=False)
    async def get_openapi_ru() -> JSONResponse:
        return JSONResponse(build_localised_openapi(app, "ru"))

    @app.get("/openapi.de.json", include_in_schema=False)
    async def get_openapi_de() -> JSONResponse:
        return JSONResponse(build_localised_openapi(app, "de"))

    @app.get("/openapi.fr.json", include_in_schema=False)
    async def get_openapi_fr() -> JSONResponse:
        return JSONResponse(build_localised_openapi(app, "fr"))

    @app.get("/docs/ru", include_in_schema=False, response_class=HTMLResponse)
    async def swagger_ui_ru() -> HTMLResponse:
        return swagger_ui_html("/openapi.ru.json", "SMDG API — Русская документация")

    @app.get("/docs/de", include_in_schema=False, response_class=HTMLResponse)
    async def swagger_ui_de() -> HTMLResponse:
        return swagger_ui_html("/openapi.de.json", "SMDG API — Deutsche Dokumentation")

    @app.get("/docs/fr", include_in_schema=False, response_class=HTMLResponse)
    async def swagger_ui_fr() -> HTMLResponse:
        return swagger_ui_html("/openapi.fr.json", "SMDG API — Documentation française")
