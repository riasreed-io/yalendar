from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


def make_id(source: str, source_id: str, start_iso: str) -> str:
    raw = f"{source}|{source_id}|{start_iso}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def fingerprint(title: str, start_iso: str, location: str) -> str:
    norm_title = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
    norm_loc = re.sub(r"[^a-z0-9]+", " ", (location or "").lower()).strip()[:40]
    minute = start_iso[:16] if start_iso else ""
    raw = f"{norm_title}|{minute}|{norm_loc}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


@dataclass
class Event:
    id: str
    source: str
    source_id: str
    title: str
    start: str
    end: str | None
    all_day: bool
    location: str
    description: str
    url: str
    host: str
    tags: str
    fingerprint: str
    canonical_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        row = asdict(self)
        extra = row.pop("extra")
        row["all_day"] = 1 if self.all_day else 0
        row["extra_json"] = extra
        return row
