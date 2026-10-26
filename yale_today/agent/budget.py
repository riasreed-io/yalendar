"""A spend ceiling for the whole deployment, not just for one question.

agent.py already caps a single question at six requests and $0.25. That
stops a runaway loop inside one run. It does nothing at all about the other
shape of the problem: a script calling /api/agent ten thousand times. Each
call is individually within its limit, and the bill is $2,500.

So this is the second ceiling. Every answered question is written to a
small SQLite file with its estimated cost, and three limits are checked
before the model is ever built:

  * questions per day, across everyone
  * estimated dollars per day, across everyone
  * questions per hour from one caller

When a limit is hit the question still gets answered -- by the free local
search, which needs no model and costs nothing. Refusing outright would
turn a budget cap into an outage.

The counters live in their own file rather than in events.db, because the
demo build rewrites events.db from the snapshot on every boot and would
reset the budget with it. Honest limitation: the file is per-machine, so a
deployment that runs several machines gets that multiple of the ceiling,
and a machine that restarts starts the day's count again.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import timedelta

from ..config import DATA_DIR, now_local

USAGE_DB = DATA_DIR / "agent_usage.db"


def _limit(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


MAX_QUESTIONS_PER_DAY = int(_limit("YALENDAR_MAX_QUESTIONS_PER_DAY", 60))
MAX_COST_PER_DAY_USD = _limit("YALENDAR_MAX_COST_PER_DAY", 0.10)
MAX_QUESTIONS_PER_IP_PER_HOUR = int(_limit("YALENDAR_MAX_QUESTIONS_PER_HOUR", 5))

# The ceiling that actually bounds the bill. A daily cap is a recurring
# charge: $0.10 a day is $36 a year for a project nobody is paying for.
# This is a total, for the life of the deployment. When it is reached the
# agent stops costing anything, permanently, until someone raises it on
# purpose. At the measured $0.00076 a question, 25 cents is roughly 330
# questions -- the per-day count runs out long before the money does.
MAX_COST_TOTAL_USD = _limit("YALENDAR_MAX_COST_TOTAL", 0.25)

# Per million tokens, gpt-6-luna at the course rate. Used to estimate what
# has been spent, so the ceiling degrades safely: if these drift low, the
# cap trips late rather than never.
PRICE_IN = 0.10
PRICE_CACHED = 0.01
PRICE_CACHE_WRITE = 0.125
PRICE_OUT = 0.50

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    caller TEXT NOT NULL DEFAULT '',
    cost_usd REAL NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_agent_calls_at ON agent_calls(at);
"""


def _usd(amount: float) -> str:
    """Two decimals for real money, four for the tiny values a test uses.
    A flat :.2f renders a $0.002 ceiling as "$0.00", which reads as a bug."""
    return f"${amount:.2f}" if amount >= 0.01 else f"${amount:.4f}"


@dataclass
class Allowance:
    ok: bool
    reason: str = ""
    questions_today: int = 0
    spent_today: float = 0.0
    spent_total: float = 0.0


def _con() -> sqlite3.Connection:
    USAGE_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(USAGE_DB, check_same_thread=False)
    con.executescript(SCHEMA)
    return con


def estimate_cost(usage: dict) -> float:
    """Dollars for one run from its measured token counts.

    input_tokens is *inclusive* of cached reads and cache writes, so the
    plain input rate applies only to the remainder. Billing them twice
    would overstate every number in the writeup.
    """
    cached = usage.get("cache_read_tokens") or 0
    written = usage.get("cache_write_tokens") or 0
    fresh = max((usage.get("input_tokens") or 0) - cached - written, 0)
    out = usage.get("output_tokens") or 0
    return (
        fresh * PRICE_IN
        + cached * PRICE_CACHED
        + written * PRICE_CACHE_WRITE
        + out * PRICE_OUT
    ) / 1_000_000


def check(caller: str = "") -> Allowance:
    """Decide whether one more billed question is allowed right now."""
    now = now_local()
    day = now.date().isoformat()
    hour_ago = (now - timedelta(hours=1)).isoformat()

    con = _con()
    count, spent = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(cost_usd), 0) FROM agent_calls "
        "WHERE substr(at, 1, 10) = ?",
        (day,),
    ).fetchone()
    lifetime = con.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM agent_calls"
    ).fetchone()[0]
    from_caller = con.execute(
        "SELECT COUNT(*) FROM agent_calls WHERE caller = ? AND at >= ?",
        (caller, hour_ago),
    ).fetchone()[0]
    con.close()

    # Checked first: it is the only limit that bounds the total bill
    # rather than the rate of spending.
    if lifetime >= MAX_COST_TOTAL_USD:
        return Allowance(False, f"the {_usd(MAX_COST_TOTAL_USD)} total AI budget "
                                "for this deployment is spent", count, spent,
                                lifetime)
    if count >= MAX_QUESTIONS_PER_DAY:
        return Allowance(False, f"daily limit of {MAX_QUESTIONS_PER_DAY} "
                                "AI questions reached", count, spent, lifetime)
    if spent >= MAX_COST_PER_DAY_USD:
        return Allowance(False, f"daily AI budget of {_usd(MAX_COST_PER_DAY_USD)} "
                                "reached", count, spent, lifetime)
    if caller and from_caller >= MAX_QUESTIONS_PER_IP_PER_HOUR:
        return Allowance(False, f"hourly limit of {MAX_QUESTIONS_PER_IP_PER_HOUR} "
                                "AI questions per visitor reached", count, spent,
                                lifetime)
    return Allowance(True, "", count, spent, lifetime)


def record(caller: str, usage: dict) -> float:
    """Log one answered question. Returns its estimated cost."""
    cost = estimate_cost(usage or {})
    con = _con()
    with con:
        con.execute(
            "INSERT INTO agent_calls (at, caller, cost_usd, total_tokens) "
            "VALUES (?, ?, ?, ?)",
            (now_local().isoformat(timespec="seconds"), caller or "", cost,
             int((usage or {}).get("total_tokens") or 0)),
        )
    con.close()
    return cost


def status() -> dict:
    allowance = check()
    return {
        "questions_today": allowance.questions_today,
        "spent_today_usd": round(allowance.spent_today, 4),
        "spent_total_usd": round(allowance.spent_total, 4),
        "max_cost_total_usd": MAX_COST_TOTAL_USD,
        "max_questions_per_day": MAX_QUESTIONS_PER_DAY,
        "max_cost_per_day_usd": MAX_COST_PER_DAY_USD,
        "max_questions_per_visitor_per_hour": MAX_QUESTIONS_PER_IP_PER_HOUR,
        "blocked": not allowance.ok,
        "reason": allowance.reason,
    }
