from __future__ import annotations

import json
from collections import defaultdict
from .db import connect
from .models import fingerprint


def apply_dedupe(path=None) -> int:
    """Group near-duplicate events; keep earliest source as canonical."""
    con = connect(path)
    rows = con.execute(
        "SELECT id, source, title, start, location, fingerprint FROM events"
    ).fetchall()
    buckets: dict[str, list] = defaultdict(list)
    for row in rows:
        key = fingerprint(row["title"], row["start"][:16] if row["start"] else "")
        buckets[key].append(row)

    updated = 0
    source_rank = {
        "localist": 0,
        "yale_connect": 1,
        "campus_groups": 2,
        "nhfpl": 3,
        "unh": 4,
        "athletics": 5,
        "ics": 6,
    }
    with con:
        for group in buckets.values():
            group.sort(
                key=lambda r: (
                    source_rank.get(r["source"], 9),
                    r["start"] or "",
                    r["id"],
                )
            )
            canonical = group[0]["id"]
            for row in group:
                cid = canonical if len(group) > 1 else None
                if row["id"] == canonical:
                    cid = None if len(group) == 1 else canonical
                con.execute("UPDATE events SET canonical_id=? WHERE id=?", (cid, row["id"]))
                updated += 1
    con.close()
    return updated


def events_for_day(day: str, source: str | None = None, q: str | None = None, path=None):
    return events_for_range(day, day, source=source, q=q, path=path)


def events_for_range(
    start_day: str,
    end_day: str,
    source: str | None = None,
    q: str | None = None,
    path=None,
):
    """Canonical events with start date from start_day through end_day inclusive."""
    con = connect(path)
    clauses = ["substr(start, 1, 10) >= ?", "substr(start, 1, 10) <= ?"]
    args: list = [start_day, end_day]
    if source:
        clauses.append("source = ?")
        args.append(source)
    if q:
        like = f"%{q.strip()}%"
        clauses.append("(title LIKE ? OR host LIKE ? OR location LIKE ? OR tags LIKE ?)")
        args.extend([like, like, like, like])
    sql = f"""
        SELECT * FROM events
        WHERE {' AND '.join(clauses)}
        ORDER BY start, title
    """
    rows = [dict(r) for r in con.execute(sql, args).fetchall()]
    con.close()

    seen_fp: set[str] = set()
    unique = []
    also: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        fp = row["fingerprint"]
        if row["canonical_id"] and row["canonical_id"] != row["id"]:
            also[row["canonical_id"]].append(row["source"])
            continue
        if fp in seen_fp:
            continue
        seen_fp.add(fp)
        unique.append(row)
    for row in unique:
        extras = also.get(row["id"], [])
        row["also_listed"] = extras
    return unique
