#!/usr/bin/env python
"""Measure what one question to the Yalendar agent actually costs.

Two modes.

    python scripts/measure_tokens.py --offline

Counts the input side with tiktoken against the real system prompt, the real
tool schemas and a real tool result. Needs no API key and spends nothing. It
cannot tell you output tokens, because those depend on what the model writes
back -- and on a reasoning model, most of them are thinking tokens you never
see.

    python scripts/measure_tokens.py --live

Runs the sample questions through the real model, reads the token counts
back off each result, and prints measured cost per run and per user per
month. Appends every run to output/audit_trail.json. Needs OPENAI_API_KEY
in .env. At gpt-5-mini with web search off this costs a few cents in total.

Prices are per million tokens and change; override with --price-in /
--price-cached / --price-out rather than trusting the defaults.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yale_today.agent.agent import (  # noqa: E402
    AUDIT_PATH,
    DEFAULT_MODEL,
    WEB_SEARCH_DEFAULT,
    load_prompt,
)
from yale_today.agent.tools import ALL_TOOLS, search_events_in_words  # noqa: E402

# A spread of what students actually type, not six variations of one shape.
QUESTIONS = [
    "free food this week",
    "what's happening tonight",
    "any talks at the law school next week",
    "SOM events on Friday",
    "concerts or performances this weekend",
    "is there anything for first-years today",
    "workshops about careers in the next two weeks",
    "what's on at the Schwarzman Center",
    "anything in New Haven off campus this weekend",
    "when is the next home football game",
]

# Per million tokens. Defaults are gpt-5-mini at the time of writing.
PRICE_IN = 0.25
PRICE_CACHED = 0.025
PRICE_OUT = 2.00
# Billed per call, on top of tokens, if the native web_search is enabled.
PRICE_WEB_SEARCH_PER_CALL = 0.01


def _enc():
    import tiktoken

    return tiktoken.get_encoding("o200k_base")


def offline() -> None:
    enc = _enc()
    n = lambda s: len(enc.encode(s))  # noqa: E731

    prompt = n(load_prompt())
    schemas = sum(
        n(f.__name__ + "\n" + (inspect.getdoc(f) or "") + "\n" + str(inspect.signature(f)))
        for f in ALL_TOOLS
    )
    result = search_events_in_words("free food this week")
    payload = n(result.model_dump_json())
    question = n(QUESTIONS[0])

    turn1 = prompt + schemas + question
    turn2 = turn1 + payload + 60  # + the assistant's own tool-call message

    print("measured offline with tiktoken (o200k_base)\n")
    print(f"  system prompt            {prompt:7,d} tok")
    print(f"  tool schemas (4 tools)   {schemas:7,d} tok")
    print(f"  one tool result          {payload:7,d} tok"
          f"   ({result.returned} of {result.total} events)")
    print(f"  user question            {question:7,d} tok")
    print(f"  {'-' * 40}")
    print(f"  turn 1 input             {turn1:7,d} tok")
    print(f"  turn 2 input             {turn2:7,d} tok")
    print(f"  INPUT PER RUN            {turn1 + turn2:7,d} tok")
    print(f"  of which cacheable       {prompt + schemas:7,d} tok"
          "   (identical on every run)")
    print("\n  output tokens: unknown offline. Run with --live.")

    # What the payload trimming is worth, measured rather than asserted.
    from datetime import timedelta

    from yale_today.config import today_local
    from yale_today.dedupe import events_for_range
    from yale_today.facets import enrich

    first = today_local()
    rows = events_for_range(first.isoformat(), (first + timedelta(days=6)).isoformat())
    enrich(rows)
    raw = n(json.dumps(rows, default=str))
    print(f"\n  one week of raw DB rows  {raw:9,d} tok  ({len(rows)} events)")
    print(f"  same week, trimmed       {payload:9,d} tok  ({result.returned} events)")
    print(f"  reduction                {raw / max(payload, 1):9,.0f}x")


def live(args: argparse.Namespace) -> None:
    from yale_today.agent.agent import run_agent

    rows = []
    print(f"model {args.model or DEFAULT_MODEL}  web_search={WEB_SEARCH_DEFAULT}\n")
    for q in QUESTIONS[: args.n]:
        before = _audit_len()
        try:
            run_agent(q)
        except Exception as exc:
            print(f"  FAILED  {q}\n          {exc.__class__.__name__}: {exc}")
            continue
        entry = _last_audit(before)
        if not entry:
            continue
        usage = entry.get("usage") or {}
        rows.append(usage)
        print(f"  {usage.get('input_tokens', 0):6,d} in  "
              f"{usage.get('cache_read_tokens', 0):6,d} cached  "
              f"{usage.get('output_tokens', 0):6,d} out  "
              f"{entry.get('seconds', 0):5.1f}s  "
              f"{len(entry.get('tool_calls') or [])} tools  |  {q}")

    if not rows:
        print("\nno successful runs")
        return

    k = len(rows)
    avg = lambda key: sum(r.get(key, 0) or 0 for r in rows) / k  # noqa: E731
    inp, cached, out = avg("input_tokens"), avg("cache_read_tokens"), avg("output_tokens")
    fresh = max(inp - cached, 0)
    cost = (fresh * args.price_in + cached * args.price_cached
            + out * args.price_out) / 1_000_000
    if WEB_SEARCH_DEFAULT:
        cost += PRICE_WEB_SEARCH_PER_CALL

    print(f"\naverages over {k} runs")
    print(f"  input           {inp:9,.0f} tok  ({cached:,.0f} cached, {fresh:,.0f} fresh)")
    print(f"  output          {out:9,.0f} tok")
    print(f"  cost per run    ${cost:9.5f}")
    print("\nat these numbers")
    for q_per_month in (3, 5, 10):
        per_user = cost * q_per_month
        print(f"  {q_per_month:2d} questions/user/month   "
              f"${per_user:7.4f}/user   "
              f"${per_user * 100:9,.2f}/mo at 100 users   "
              f"${per_user * 10_000:11,.2f}/mo at 10,000")
    print(f"\nfull detail in {AUDIT_PATH}")


def _audit_len() -> int:
    if not AUDIT_PATH.is_file():
        return 0
    try:
        return len(json.loads(AUDIT_PATH.read_text() or "[]"))
    except ValueError:
        return 0


def _last_audit(before: int) -> dict | None:
    try:
        entries = json.loads(AUDIT_PATH.read_text() or "[]")
    except (OSError, ValueError):
        return None
    return entries[-1] if len(entries) > before else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="make real model calls")
    ap.add_argument("--offline", action="store_true", help="tiktoken only, free")
    ap.add_argument("-n", type=int, default=len(QUESTIONS), help="how many questions")
    ap.add_argument("--model", default="", help="override YALENDAR_MODEL")
    ap.add_argument("--price-in", type=float, default=PRICE_IN)
    ap.add_argument("--price-cached", type=float, default=PRICE_CACHED)
    ap.add_argument("--price-out", type=float, default=PRICE_OUT)
    args = ap.parse_args()

    if args.model:
        import os

        os.environ["YALENDAR_MODEL"] = args.model

    if args.live:
        live(args)
    else:
        offline()


if __name__ == "__main__":
    main()
