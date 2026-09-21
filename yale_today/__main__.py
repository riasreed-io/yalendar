from __future__ import annotations

import argparse
import os

import uvicorn

from .auth import password_file
from .ingest import run_ingest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Yale Today campus events dashboard")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ingest_p = sub.add_parser("ingest", help="Pull Localist, Yale Connect, and ICS feeds")
    ingest_p.add_argument("--month", help="Limit stored events to YYYY-MM (example: 2026-09)")
    ingest_p.add_argument("--days", type=int, help="Keep events in a rolling window starting today (example: 14)")
    ingest_p.add_argument("--connect-login", action="store_true", help="Sign into Yale Connect and SOM Campus Groups")
    ingest_p.add_argument(
        "--login-source",
        action="append",
        choices=["yale_connect", "campus_groups"],
        help="Limit signed-in scrape to one platform (repeatable). Default is both.",
    )
    ingest_p.add_argument("--headed", action="store_true", help="Show the browser during Connect login (needed for Duo)")

    serve_p = sub.add_parser("serve", help="Run the private dashboard")
    serve_p.add_argument("--host", default="0.0.0.0")
    serve_p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))

    args = parser.parse_args(argv)
    if args.cmd == "ingest":
        report = run_ingest(
            include_connect_login=args.connect_login,
            headed=args.headed,
            month=getattr(args, "month", None),
            days=getattr(args, "days", None),
            login_sources=getattr(args, "login_source", None),
        )
        print(report.as_dict())
        return
    path = password_file()
    print(f"Dashboard password is in {path}")
    print(f"Open http://{args.host}:{args.port}/")
    uvicorn.run("yale_today.web:app", host=args.host, port=args.port, reload=os.environ.get("YALE_TODAY_RELOAD") == "1")


if __name__ == "__main__":
    main()
