#!/usr/bin/env python3
"""
Генерация static/manifest.json и копий файлов с fingerprint в имени (для S3/CloudFront).
Использование: python scripts/generate_asset_manifest.py [path/to/static]
"""
from __future__ import annotations

import sys
from pathlib import Path

# корень репозитория
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.asset_pipeline import AssetPipeline  # noqa: E402


def main() -> None:
    static_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else (_ROOT / "static").resolve()
    if not static_dir.is_dir():
        print(f"Not a directory: {static_dir}", file=sys.stderr)
        sys.exit(1)

    ap = AssetPipeline(
        static_dir,
        "/static/",
        cdn_url=None,
        auto_generate=False,
        fingerprinting=True,
    )
    ap.generate_manifest()
    print(f"OK: manifest {ap.manifest_file} ({len(ap.manifest)} entries)")


if __name__ == "__main__":
    main()
