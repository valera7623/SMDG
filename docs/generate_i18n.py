#!/usr/bin/env python3
"""Synchronise documentation translations.

This script keeps the English source documentation under ``docs/src/``
in sync with the translation directories under ``docs/locales/<lang>/``.

Behaviour:

* For every ``<name>.md`` under ``docs/src/`` it ensures an equivalent
  file exists in each target locale.
* Missing translation files are created from a stub that contains a
  TODO header, the sync date, the SHA-1 of the source file and the
  first ~200 characters of the source body as a preview.
* Translation files whose header SHA-1 no longer matches the current
  English source are flagged as ``stale`` and the header is refreshed
  (the existing translated body is kept).
* The script exits with a non-zero status code when ``--strict`` is
  passed and any translation is missing or stale, which makes it
  suitable for CI.

The script uses only the Python standard library — no third-party
dependencies are required.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


SUPPORTED_LANGS: tuple[str, ...] = ("ru", "de", "fr")
LANG_DISPLAY = {
    "ru": "Russian",
    "de": "German",
    "fr": "French",
}

HEADER_START = "<!-- smdg-i18n-header-start"
HEADER_END = "smdg-i18n-header-end -->"
HEADER_PATTERN = re.compile(
    re.escape(HEADER_START) + r".*?" + re.escape(HEADER_END),
    re.DOTALL,
)


@dataclass
class SyncReport:
    """Aggregated outcome of a sync run."""

    created: list[Path] = field(default_factory=list)
    stale: list[Path] = field(default_factory=list)
    up_to_date: list[Path] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.created or self.stale)

    def print_summary(self) -> None:
        print("\n=== SMDG i18n sync report ===")
        print(f"  created    : {len(self.created)}")
        print(f"  stale      : {len(self.stale)}")
        print(f"  up-to-date : {len(self.up_to_date)}")
        for bucket, items in (
            ("NEW", self.created),
            ("STALE", self.stale),
        ):
            if not items:
                continue
            print(f"\n{bucket}:")
            for path in items:
                print(f"  - {path}")


def sha1(text: str) -> str:
    """Return the hex SHA-1 of ``text`` encoded as UTF-8."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()  # noqa: S324


def make_header(source_rel: Path, source_hash: str, lang: str) -> str:
    """Build the localisation header prepended to stub/translated files."""
    today = _dt.date.today().isoformat()
    return (
        f"{HEADER_START}\n"
        f"source: {source_rel.as_posix()}\n"
        f"source_sha1: {source_hash}\n"
        f"language: {lang}\n"
        f"last_sync: {today}\n"
        f"status: needs-translation\n"
        f"{HEADER_END}"
    )


def parse_header(text: str) -> dict[str, str] | None:
    """Return the header fields if present, otherwise ``None``."""
    match = HEADER_PATTERN.search(text)
    if not match:
        return None
    body = match.group(0)
    fields: dict[str, str] = {}
    for line in body.splitlines():
        line = line.strip()
        if ":" not in line or line.startswith("<!--") or line.endswith("-->"):
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def build_stub(source_path: Path, source_rel: Path, lang: str) -> str:
    """Return the full stub text for a missing translation file."""
    source_text = source_path.read_text(encoding="utf-8")
    source_hash = sha1(source_text)
    header = make_header(source_rel, source_hash, lang)
    preview = source_text.strip()[:200].replace("\n", " ")
    lang_name = LANG_DISPLAY.get(lang, lang)
    return (
        f"{header}\n\n"
        f"> **TODO**: Translate this file into {lang_name} from "
        f"`{source_rel.as_posix()}`.\n"
        f"> Remove this TODO banner once the translation is complete.\n\n"
        f"*[This page requires translation from English.]*\n\n"
        f"---\n\n"
        f"**English source preview:**\n\n"
        f"{preview}…\n"
    )


def refresh_header(existing: str, source_path: Path, source_rel: Path, lang: str) -> str:
    """Replace the existing header with an up-to-date one, keep the body."""
    source_hash = sha1(source_path.read_text(encoding="utf-8"))
    new_header = make_header(source_rel, source_hash, lang)
    if HEADER_PATTERN.search(existing):
        return HEADER_PATTERN.sub(new_header, existing, count=1)
    return f"{new_header}\n\n{existing}"


def iter_source_files(src_dir: Path) -> Iterable[Path]:
    yield from sorted(src_dir.glob("*.md"))


def sync(
    src_dir: Path,
    locales_dir: Path,
    langs: Iterable[str],
    dry_run: bool = False,
) -> SyncReport:
    """Synchronise ``src_dir`` into every ``locales_dir/<lang>`` folder."""
    report = SyncReport()

    for lang in langs:
        target_dir = locales_dir / lang
        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)

        for source_path in iter_source_files(src_dir):
            source_rel = Path("docs/src") / source_path.name
            target_path = target_dir / source_path.name

            if not target_path.exists():
                report.created.append(target_path)
                if not dry_run:
                    target_path.write_text(
                        build_stub(source_path, source_rel, lang),
                        encoding="utf-8",
                    )
                continue

            existing_text = target_path.read_text(encoding="utf-8")
            header = parse_header(existing_text)
            source_hash = sha1(source_path.read_text(encoding="utf-8"))

            if header and header.get("source_sha1") == source_hash:
                report.up_to_date.append(target_path)
                continue

            report.stale.append(target_path)
            if not dry_run:
                refreshed = refresh_header(
                    existing_text, source_path, source_rel, lang
                )
                target_path.write_text(refreshed, encoding="utf-8")

    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronise SMDG documentation translations.",
    )
    parser.add_argument(
        "--src",
        type=Path,
        default=Path(__file__).resolve().parent / "src",
        help="Path to the English source directory (default: docs/src).",
    )
    parser.add_argument(
        "--locales",
        type=Path,
        default=Path(__file__).resolve().parent / "locales",
        help="Path to the locales directory (default: docs/locales).",
    )
    parser.add_argument(
        "--langs",
        nargs="+",
        default=list(SUPPORTED_LANGS),
        help=f"Languages to sync (default: {' '.join(SUPPORTED_LANGS)}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing any files.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with status 1 when any translation is missing or stale.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.src.is_dir():
        print(f"error: source directory {args.src} does not exist", file=sys.stderr)
        return 2

    report = sync(args.src, args.locales, args.langs, dry_run=args.dry_run)
    report.print_summary()

    if args.strict and report.has_changes:
        print(
            "\nstrict mode: translations are missing or stale — failing the run.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
