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

    setup_p = sub.add_parser(
        "setup",
        help="First run: pull the public calendars, then optionally sign in",
    )
    setup_p.add_argument("--days", type=int, default=45,
                         help="How many days ahead to pull (default 45)")
    setup_p.add_argument("--yes", action="store_true",
                         help="Take the defaults; never prompt")

    sub.add_parser("mode", help="Show which build this is and what it may do")

    sub.add_parser(
        "login",
        help="Sign into Yale Connect and Campus Groups once; the session is saved for later runs",
    )
    sub.add_parser("login-check", help="Verify the saved signed-in session still works")
    harvest_p = sub.add_parser(
        "harvest", help="Pull signed-in events using the saved session (no Duo)")
    harvest_p.add_argument("--month", help="Limit to YYYY-MM")

    serve_p = sub.add_parser("serve", help="Run the private dashboard")
    serve_p.add_argument("--host", default="0.0.0.0")
    serve_p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))

    args = parser.parse_args(argv)

    if args.cmd == "setup":
        import sys

        from .setup_wizard import run as run_setup

        raise SystemExit(run_setup(
            interactive=not args.yes and sys.stdin.isatty(), days=args.days))

    if args.cmd == "mode":
        from .config import (
            DATA_DIR, DB_PATH, MODE, network_allowed, personal_files_present,
            signin_allowed, today_local, writes_allowed,
        )

        print(f"mode            {MODE}")
        print(f"data folder     {DATA_DIR}")
        print(f"database        {DB_PATH}")
        print(f"'today' is      {today_local()}")
        print(f"may fetch       {network_allowed()}")
        print(f"may write       {writes_allowed()}")
        print(f"may sign in     {signin_allowed()}")
        stray = personal_files_present()
        if stray and MODE != "personal":
            print("WARNING         a Yale session is visible to this build: "
                  + ", ".join(p.name for p in stray))
        return

    if args.cmd in {"login", "login-check", "harvest"}:
        from . import session_login

        if args.cmd == "login":
            report = session_login.interactive_login()
        elif args.cmd == "login-check":
            report = session_login.check_session()
        else:
            events, report = session_login.harvest(month=getattr(args, "month", "") or "")
            print(f"Pulled {len(events)} signed-in events.")

        print("\nSigned-in status")
        print("-" * 56)
        for check in report.checks:
            mark = "OK  " if check.signed_in else "FAIL"
            extra = f" ({check.private_rows} sign-in-only)" if check.private_rows else ""
            print(f"  [{mark}] {check.name:22} {check.rows:4d} events{extra}  {check.detail}")
        if not report.ok:
            print("\nRun `python -m yale_today login` to sign in.")
        return

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
