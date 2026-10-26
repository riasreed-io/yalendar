from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


def make_id(source: str, source_id: str, start_iso: str) -> str:
    raw = f"{source}|{source_id}|{start_iso}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


# Bump when fingerprint() changes, so db.connect() can recompute stored
# values instead of silently mixing two generations of hash.
FINGERPRINT_VERSION = 2


def fingerprint(title: str, start_iso: str) -> str:
    """Identity of an event across sources: normalised title + start minute.

    Location is deliberately NOT part of this. Every calendar spells the same
    room differently -- one real event was listed as "Winslow Auditorium",
    "Winslow Auditorium 60 College Street" and "Yale School of Public Health
    Winslow Aud" -- and two sources emit placeholder strings ("Sign in to
    download the location") in the location field at all. Including it split
    637 groups that are one event, which is why a single talk showed up to
    five times in the feed. Of those 637, only 27 joined venues that were not
    plainly the same place written two ways.
    """
    norm_title = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
    minute = start_iso[:16] if start_iso else ""
    raw = f"{norm_title}|{minute}"
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
