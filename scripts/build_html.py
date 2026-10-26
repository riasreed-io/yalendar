#!/usr/bin/env python
"""Turn the report and slide templates into self-contained HTML.

    python scripts/build_html.py

Every {{IMG:name.png}} in a template is replaced with a base64 data URI of
docs/name.png, so report.html and slides.html open by double-clicking on
any machine with every screenshot intact -- which is what the assignment
asks for, and what a file full of <img src="docs/..."> would fail the
moment it was uploaded anywhere.
"""

from __future__ import annotations

import base64
import mimetypes
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
TARGETS = [
    (DOCS / "report.template.html", ROOT / "report.html"),
    (DOCS / "slides.template.html", ROOT / "slides.html"),
]
PLACEHOLDER = re.compile(r"\{\{IMG:([^}]+)\}\}")


def data_uri(name: str) -> str:
    path = DOCS / name
    if not path.is_file():
        raise SystemExit(f"missing image: {path}")
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def build(src: Path, out: Path) -> None:
    if not src.is_file():
        print(f"  skip {src.name} (not written yet)")
        return
    html = src.read_text(encoding="utf-8")
    used: list[str] = []

    def swap(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        used.append(name)
        return data_uri(name)

    html = PLACEHOLDER.sub(swap, html)
    out.write_text(html, encoding="utf-8")
    size = out.stat().st_size / 1_048_576
    print(f"  {out.name}: {size:.2f} MB, {len(used)} images embedded")
    if PLACEHOLDER.search(html):
        raise SystemExit(f"{out.name} still has unreplaced placeholders")
    if "docs/" in html and "data:image" in html:
        leftovers = re.findall(r'src="(?!data:)[^"]+"', html)
        if leftovers:
            raise SystemExit(f"{out.name} references external files: {leftovers[:3]}")


def main() -> None:
    print("building self-contained HTML")
    for src, out in TARGETS:
        build(src, out)


if __name__ == "__main__":
    sys.exit(main())
