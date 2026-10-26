"""First-run setup for somebody who is not me.

Everything this does was already possible with three separate commands and
a reading of the README. The reason it exists as one command is that the
hard part of handing this project to another student was never the code --
it was knowing that the public sources need nothing, that signing in is
optional, and that the sign-in happens on Yale's own page and not in mine.
A wizard can say that at the moment it matters instead of in a document
nobody opens.

Nothing here reads, types or stores a credential.
"""

from __future__ import annotations

import sys

from .config import DATA_DIR, DB_PATH, MODE, SESSION_STATE_PATH, signin_allowed

RULE = "-" * 66


def _say(text: str = "") -> None:
    print(text, flush=True)


def _ask(question: str, default: bool, interactive: bool) -> bool:
    if not interactive:
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{question} {suffix} ").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer.startswith("y")


def run(interactive: bool = True, days: int = 45) -> int:
    _say(RULE)
    _say("Yalendar setup")
    _say(RULE)
    _say(f"  mode          {MODE}")
    _say(f"  data folder   {DATA_DIR}")
    _say(f"  database      {DB_PATH.name}")
    _say()

    # 1 -- public sources. No account, no key, no questions asked.
    _say("Step 1 of 3: pulling the public calendars.")
    _say("  Yale Events, the school Localist instances, Yale Connect and SOM")
    _say("  Campus Groups' public listings, athletics, the residential college")
    _say("  feed, and two New Haven calendars. None of these need an account.")
    _say("  This takes a couple of minutes.")
    _say()
    from .ingest import run_ingest

    try:
        report = run_ingest(include_connect_login=False, days=days)
    except Exception as exc:
        _say(f"  FAILED: {exc.__class__.__name__}: {exc}")
        return 1
    _say(f"  Stored {report.total_upserted:,} events.")
    for err in report.errors:
        _say(f"  warning: {err}")
    _say()

    # 2 -- the optional half.
    _say("Step 2 of 3: your own Yale sign-in (optional).")
    if not signin_allowed():
        _say(f"  Skipped: not available in {MODE} mode.")
    else:
        _say("  Yale Connect and SOM Campus Groups blank out the venue for")
        _say("  logged-out visitors and hide members-only club events. Signing")
        _say("  in fixes both.")
        _say()
        _say("  Yalendar has no password field and never sees your NetID. A")
        _say("  Chrome window opens on YOUR computer at Yale's own CAS page;")
        _say("  you type there, Duo goes to your phone, and the only thing")
        _say(f"  kept is a cookie in {SESSION_STATE_PATH.name}, on this disk.")
        _say()
        if SESSION_STATE_PATH.is_file():
            _say("  A saved session already exists here.")
        if _ask("  Open the Yale sign-in window now?", default=False,
                interactive=interactive):
            from . import session_login

            report_login = session_login.interactive_login()
            for check in report_login.checks:
                mark = "OK  " if check.signed_in else "FAIL"
                _say(f"  [{mark}] {check.name}: {check.detail}")
            if report_login.ok:
                _say("  Pulling the signed-in events...")
                events, _ = session_login.harvest()
                _say(f"  Added {len(events):,}.")
        else:
            _say("  Skipped. Run `python -m yale_today login` whenever you like.")
    _say()

    # 3 -- personal feeds, which need no credential at all.
    _say("Step 3 of 3: personal iCal feeds (optional).")
    _say("  Any ICS subscription URL: a club calendar, your college, a Google")
    _say("  Calendar you own. Add them on the Connect page once the site is up.")
    _say()

    _say(RULE)
    _say("Done. Start it with:")
    _say()
    _say("    python -m yale_today serve")
    _say()
    _say("Then open http://127.0.0.1:8000/")
    _say(RULE)
    return 0


def main() -> int:
    return run(interactive=sys.stdin.isatty())
