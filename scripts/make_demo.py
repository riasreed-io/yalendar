#!/usr/bin/env python
"""Build the shareable demo snapshot: demo/snapshot.json.gz.

    python scripts/make_demo.py --rebuild        # fetch, then export
    python scripts/make_demo.py --from <db>      # export an existing public DB
    python scripts/make_demo.py --inspect        # what is in the current one

--rebuild does the ingest in a throwaway data directory with
YALENDAR_MODE=public, which disables every signed-in source in code. That
is the point: the snapshot contains only what an anonymous visitor could
have fetched themselves, and it is public *by construction* rather than by
me filtering the live database afterwards and hoping I guessed right about
which rows were private.

The result is committed. Anyone who clones the repo can run

    YALENDAR_MODE=demo python -m yale_today serve

and get a fully populated calendar with no Yale account, no API key and no
network.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_DAYS = 45


def rebuild(days: int) -> Path:
    scratch = Path(tempfile.mkdtemp(prefix="yalendar-demo-"))
    print(f"scratch data dir: {scratch}")
    env = {
        **os.environ,
        "YALE_TODAY_DATA": str(scratch),
        # public mode: ingest() refuses a signed-in pull and session_login
        # refuses to open a browser, so nothing private can enter this DB.
        "YALENDAR_MODE": "public",
    }
    env.pop("YALENDAR_MODEL", None)
    print(f"ingesting {days} days of public sources (a few minutes)...")
    proc = subprocess.run(
        [sys.executable, "-m", "yale_today", "ingest", "--days", str(days)],
        cwd=ROOT, env=env, text=True, capture_output=True,
    )
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        shutil.rmtree(scratch, ignore_errors=True)
        raise SystemExit(f"ingest failed ({proc.returncode})")
    return scratch / "events.db"


def inspect() -> None:
    from yale_today import demo
    from yale_today.config import DEMO_SNAPSHOT

    if not DEMO_SNAPSHOT.is_file():
        raise SystemExit(f"no snapshot at {DEMO_SNAPSHOT}")
    payload = demo.load(DEMO_SNAPSHOT)
    meta = payload["meta"]
    print(json.dumps(meta, indent=2))
    by_source: dict[str, int] = {}
    for event in payload["events"]:
        by_source[event["source"]] = by_source.get(event["source"], 0) + 1
    print("\nevents by source")
    for source, n in sorted(by_source.items(), key=lambda kv: -kv[1]):
        print(f"  {n:6,d}  {source}")
    size = DEMO_SNAPSHOT.stat().st_size
    print(f"\n{DEMO_SNAPSHOT.name}: {size / 1_048_576:.2f} MB on disk")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rebuild", action="store_true",
                    help="fetch public sources into a scratch dir, then export")
    ap.add_argument("--from", dest="src", default="",
                    help="export this SQLite file instead of fetching")
    ap.add_argument("--inspect", action="store_true", help="describe the current snapshot")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    args = ap.parse_args()

    if args.inspect:
        inspect()
        return
    if not args.rebuild and not args.src:
        ap.error("pass --rebuild, --from <db>, or --inspect")

    src = Path(args.src) if args.src else rebuild(args.days)
    if not src.is_file():
        raise SystemExit(f"no database at {src}")

    from yale_today import demo
    from yale_today.config import DEMO_SNAPSHOT, now_local

    meta = demo.export(
        src,
        as_of=now_local().isoformat(timespec="seconds"),
        note=f"Public Yale and New Haven sources only, {args.days} days from "
             "the snapshot date. No signed-in data, no personal calendars.",
    )
    print(f"\nwrote {DEMO_SNAPSHOT}  ({DEMO_SNAPSHOT.stat().st_size / 1_048_576:.2f} MB)")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
