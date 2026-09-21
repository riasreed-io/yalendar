from __future__ import annotations

from collections import defaultdict

CATEGORY_ORDER = [
    ("all_day", "All day & ongoing"),
    ("talks", "Talks & lectures"),
    ("arts", "Arts & performance"),
    ("exhibits", "Exhibitions"),
    ("sports", "Sports"),
    ("workshops", "Workshops & classes"),
    ("social", "Social & student life"),
    ("meetings", "Club meetings"),
    ("health", "Health & wellness"),
    ("academic", "Academic & career"),
    ("faith", "Faith & community"),
    ("other", "Other"),
]

LABELS = dict(CATEGORY_ORDER)

_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("sports", ("athletics", "sport", "game vs", "intramural", "recreation")),
    ("exhibits", ("exhibition", "exhibits", "on view", "gallery", "museum")),
    ("arts", ("performance", "concert", "music", "theatre", "theater", "drama", "film", "screening", "dance", "choir", "orchestra", "rehearsal", "audition", "tryout", "callback")),
    ("talks", ("talk", "lecture", "panel", "seminar", "colloquium", "symposium", "keynote", "town hall", "forum", "roundtable", "debate", "discussion")),
    ("workshops", ("workshop", "training", "class", "demonstration", "tutorial", "info session", "tour")),
    ("health", ("wellness", "health", "mental health", "mindfulness", "yoga", "fitness")),
    ("academic", ("deadline", "due date", "career", "fellowship", "grant", "application", "advising", "office hours", "academic")),
    ("faith", ("spiritual", "religious", "worship", "prayer", "chapel", "buddhist", "jewish", "muslim", "christian", "hillel", "mass")),
    ("social", ("social", "mixer", "reception", "networking", "game night", "student life", "meetup", "gettogether", "volunteer")),
    ("meetings", ("group meeting", "weekly meeting", "board meeting", "chapter meeting", "general meeting", "org meeting", "organization meeting", "open meeting", "club meeting")),
]


def _blob(event: dict) -> str:
    parts = [
        event.get("source") or "",
        event.get("title") or "",
        event.get("host") or "",
        event.get("tags") or "",
        event.get("location") or "",
        event.get("description") or "",
    ]
    return " ".join(parts).lower()


def classify_event(event: dict) -> str:
    if event.get("source") == "athletics":
        return "sports"
    text = _blob(event)
    if event.get("all_day") and ("exhibit" in text or "on view" in text):
        return "exhibits"
    for slug, needles in _RULES:
        if any(needle in text for needle in needles):
            return slug
    if event.get("all_day"):
        return "all_day"
    return "other"


def attach_categories(events: list[dict]) -> list[dict]:
    for event in events:
        slug = classify_event(event)
        event["category"] = slug
        event["category_label"] = LABELS.get(slug, "Other")
    return events


def group_for_day(events: list[dict], category: str | None = None) -> tuple[list[dict], list[dict]]:
    attach_categories(events)
    counts: dict[str, int] = defaultdict(int)
    for event in events:
        counts[event["category"]] += 1
    summary = [
        {"slug": slug, "label": label, "count": counts.get(slug, 0)}
        for slug, label in CATEGORY_ORDER
        if counts.get(slug, 0)
    ]
    if category:
        events = [e for e in events if e["category"] == category]
    grouped = []
    by_cat: dict[str, list] = defaultdict(list)
    for event in events:
        by_cat[event["category"]].append(event)
    for slug, label in CATEGORY_ORDER:
        rows = by_cat.get(slug) or []
        if rows:
            grouped.append({"slug": slug, "label": label, "events": rows, "count": len(rows)})
    return grouped, summary
