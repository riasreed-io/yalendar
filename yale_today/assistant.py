"""Natural-language event search for the Yalendar chat assistant.

Deterministic on purpose: no API key, no per-message cost, and nothing a
visitor can run up a bill on. The site is open to anyone with the URL.

The pipeline is deliberately split so a model-backed reply could be layered
on later without touching retrieval:

    parse(text) -> Query      # plain English to structured filters
    search(Query) -> events   # Query against the existing SQLite layer
    answer(text) -> Answer    # retrieval + phrasing for the UI

Only the last step would need to change to hand phrasing to an LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .config import TZINFO, WINDOW_DAYS, now_local
from .categories import CATEGORY_ORDER, LABELS
from .dedupe import events_for_range
from .facets import CHANNEL_LABELS, enrich

MAX_RESULTS = 8

# Words that carry no filtering signal; dropped before keyword matching.
STOPWORDS = {
    "a", "about", "am", "any", "anything", "are", "around", "at", "be", "can",
    "cool", "do", "does", "event", "events", "find", "for", "free", "from",
    "get", "going", "good", "happening", "has", "have", "how", "i", "in", "is",
    "it", "know", "like", "list", "looking", "me", "my", "near", "of", "on",
    "or", "please", "show", "some", "something", "stuff", "the", "there",
    "these", "they", "thing", "things", "this", "to", "up", "want", "was",
    "we", "what", "whats", "when", "where", "which", "who", "with", "yale",
    "you", "your",
}

# Chat synonyms onto the existing category slugs in categories.py.
CATEGORY_WORDS: list[tuple[str, tuple[str, ...]]] = [
    ("talks", ("talk", "talks", "lecture", "lectures", "panel", "panels",
               "seminar", "seminars", "colloquium", "symposium", "keynote",
               "speaker", "speakers", "debate", "discussion")),
    ("arts", ("art", "arts", "concert", "concerts", "music", "performance",
              "performances", "theater", "theatre", "play", "plays", "dance",
              "film", "films", "movie", "movies", "screening", "choir",
              "orchestra", "acapella", "improv", "comedy")),
    ("exhibits", ("exhibit", "exhibits", "exhibition", "exhibitions",
                  "gallery", "galleries", "museum", "museums")),
    ("sports", ("sport", "sports", "game", "games", "match", "soccer",
                "football", "hockey", "basketball", "volleyball", "lacrosse",
                "tennis", "crew", "rowing", "swim", "swimming", "squash",
                "baseball", "softball", "intramural", "ims", "athletics")),
    ("workshops", ("workshop", "workshops", "class", "classes", "training",
                   "tutorial", "bootcamp", "info", "tour", "tours")),
    ("social", ("social", "socials", "party", "parties", "mixer", "mixers",
                "reception", "receptions", "networking", "meetup", "hangout",
                "tailgate", "volunteer", "volunteering")),
    ("meetings", ("meeting", "meetings", "gbm", "rehearsal", "audition",
                  "auditions", "tryout", "tryouts", "callback")),
    ("health", ("wellness", "health", "mindfulness", "meditation", "yoga",
                "fitness", "gym", "workout", "therapy", "mental")),
    ("academic", ("career", "careers", "job", "jobs", "internship",
                  "internships", "recruiting", "fellowship", "grant",
                  "deadline", "deadlines", "advising", "research", "academic")),
    ("faith", ("religious", "worship", "prayer", "chapel", "mass", "shabbat",
               "hillel", "buddhist", "jewish", "muslim", "christian",
               "spiritual", "faith")),
]

# Chat synonyms onto the department slugs in facets.DEPARTMENTS.
DEPT_WORDS: list[tuple[str, tuple[str, ...]]] = [
    ("som", ("som", "management", "business", "mba")),
    ("law", ("law", "yls")),
    ("medicine", ("medicine", "medical", "ysm", "med")),
    ("nursing", ("nursing", "ysn")),
    ("public_health", ("epidemiology", "ysph")),
    ("environment", ("environment", "environmental", "yse", "forestry")),
    ("divinity", ("divinity", "yds")),
    ("drama", ("drama", "acting")),
    ("gsas", ("gsas", "grad", "graduate", "phd", "postdoc")),
    ("seas", ("engineering", "seas", "cs", "robotics")),
    ("jackson", ("jackson", "policy", "diplomacy", "geopolitics")),
    ("public_health", ("publichealth",)),
    ("college", ("college", "undergrad", "undergraduate", "freshman",
                 "firstyear", "sophomore", "junior", "senior")),
    ("libraries", ("library", "libraries", "beinecke", "bass")),
    ("cultural", ("cultural", "afam", "lacasa", "asian", "native",
                  "indigenous", "latino", "heritage")),
    ("athletics", ("bulldogs",)),
]

CHANNEL_WORDS: list[tuple[str, tuple[str, ...]]] = [
    ("campus_groups", ("campusgroups", "groups", "som")),
    ("yale_connect", ("connect", "yaleconnect", "club", "clubs", "org",
                      "orgs", "organization", "organizations", "student")),
    ("community", ("newhaven", "community", "city", "downtown", "offcampus",
                   "nhfpl", "town")),
    ("public", ("official", "public")),
]

# The single most common student query. There is no price field in the data,
# so this is a text match over title/description/tags.
FOOD_WORDS = (
    "free food", "food", "pizza", "snack", "snacks", "lunch", "dinner",
    "breakfast", "brunch", "coffee", "boba", "bagel", "bagels", "donut",
    "donuts", "cookies", "catered", "catering", "refreshments", "dessert",
    "ice cream", "tea",
)
FOOD_MATCH = (
    "food", "pizza", "snack", "lunch", "dinner", "breakfast", "brunch",
    "coffee", "boba", "bagel", "donut", "cookie", "catered", "catering",
    "refreshment", "dessert", "ice cream", "reception", "tea ", "tasting",
    "potluck", "bbq", "barbecue",
)

WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2,
    "wed": 2, "thursday": 3, "thu": 3, "thurs": 3, "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

# (from_hour, to_hour) as a half-open local-clock window.
DAYPARTS: list[tuple[str, tuple[str, ...], int, int]] = [
    ("morning", ("morning", "mornings", "am", "early"), 0, 12),
    ("afternoon", ("afternoon", "afternoons"), 12, 17),
    ("evening", ("evening", "evenings", "tonight", "night", "nights",
                 "late"), 17, 24),
    ("lunchtime", ("lunchtime", "midday", "noon"), 11, 14),
]


# Multi-word names collapsed to one token before matching, so "new haven"
# reads as a source rather than two stray keywords.
PHRASES = (
    ("new haven", "newhaven"),
    ("campus groups", "campusgroups"),
    ("public health", "publichealth"),
    ("ice cream", "icecream"),
    ("first year", "firstyear"),
    ("off campus", "offcampus"),
)

# Words that name a category but are specific enough to also be worth
# matching as text: "soccer games" should mean soccer, not all sports.
SPECIFIC = {
    "soccer", "football", "hockey", "basketball", "volleyball", "lacrosse",
    "tennis", "crew", "rowing", "squash", "baseball", "softball", "yoga",
    "meditation", "comedy", "improv", "choir", "orchestra", "acapella",
    "film", "films", "movie", "movies", "dance", "theater", "theatre",
}

# Location strings that mean "we could not read the venue".
PLACEHOLDER_LOCATION = ("sign in", "private location")


@dataclass
class Query:
    text: str
    start: date
    end: date
    span_label: str
    from_hour: int | None = None
    to_hour: int | None = None
    daypart: str = ""
    cats: list[str] = field(default_factory=list)
    depts: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    food: bool = False


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _next_weekday(today: date, target: int) -> date:
    """The next date falling on `target` weekday, today counting as a match."""
    return today + timedelta(days=(target - today.weekday()) % 7)


def _parse_span(text: str, tokens: list[str], today: date) -> tuple[date, date, str]:
    """Resolve a date range. Defaults to the coming week."""
    joined = " ".join(tokens)

    if "today" in tokens or "tonight" in tokens:
        return today, today, "today"
    if "tomorrow" in tokens or "tmrw" in tokens:
        day = today + timedelta(days=1)
        return day, day, "tomorrow"
    if "weekend" in tokens:
        saturday = _next_weekday(today, 5)
        return saturday, saturday + timedelta(days=1), "this weekend"
    if "next week" in joined:
        # Weeks run Sunday-start, matching the week view.
        sunday = _next_weekday(today, 6)
        start = sunday if today.weekday() != 6 else today + timedelta(days=7)
        return start, start + timedelta(days=6), "next week"
    if "this week" in joined or "the week" in joined:
        return today, _next_weekday(today, 5), "this week"
    if "this month" in joined or "the month" in joined:
        last = date(
            today.year + (today.month == 12),
            today.month % 12 + 1,
            1,
        ) - timedelta(days=1)
        return today, last, "the rest of this month"

    match = re.search(r"next (\d{1,2}) days?", joined)
    if match:
        span = max(1, min(WINDOW_DAYS, int(match.group(1))))
        return today, today + timedelta(days=span), f"the next {span} days"

    # "oct 3", "october 3rd", "3 oct"
    for name, number in MONTHS.items():
        match = re.search(rf"\b{name}\.?\s+(\d{{1,2}})\b", joined) or re.search(
            rf"\b(\d{{1,2}})\s+{name}\b", joined
        )
        if match:
            day_num = int(match.group(1))
            year = today.year + (1 if number < today.month - 6 else 0)
            try:
                day = date(year, number, day_num)
            except ValueError:
                break
            return day, day, day.strftime("%A, %b %-d")

    match = re.search(r"\b(\d{1,2})/(\d{1,2})\b", joined)
    if match:
        try:
            day = date(today.year, int(match.group(1)), int(match.group(2)))
            return day, day, day.strftime("%A, %b %-d")
        except ValueError:
            pass

    for name, index in WEEKDAYS.items():
        if name in tokens:
            day = _next_weekday(today, index)
            label = "today" if day == today else day.strftime("%A, %b %-d")
            return day, day, label

    # A bare month name ("anything in december") means that whole month.
    # Without this the month is ignored and the reply silently describes a
    # completely different date range.
    for name, number in MONTHS.items():
        if name not in tokens:
            continue
        year = today.year + (1 if number < today.month else 0)
        first = date(year, number, 1)
        last = date(year + (number == 12), number % 12 + 1, 1) - timedelta(days=1)
        if first <= today <= last:
            first = today
        return first, last, first.strftime("%B %Y")

    return today, today + timedelta(days=6), "the next week"


def _match_groups(tokens: list[str], table) -> list[str]:
    found: list[str] = []
    for slug, words in table:
        if any(word in tokens for word in words) and slug not in found:
            found.append(slug)
    return found


def parse(text: str, *, today: date | None = None) -> Query:
    today = today or now_local().date()
    raw = (text or "").strip()
    folded = raw.lower()
    for phrase, single in PHRASES:
        folded = folded.replace(phrase, single)
    tokens = _tokens(folded)
    joined = " ".join(tokens)

    start, end, span_label = _parse_span(raw, tokens, today)

    from_hour = to_hour = None
    daypart = ""
    for name, words, lo, hi in DAYPARTS:
        if any(word in tokens for word in words):
            from_hour, to_hour, daypart = lo, hi, name
            break
    match = re.search(r"after (\d{1,2})\s*(am|pm)?", joined)
    if match:
        hour = int(match.group(1)) % 12
        if match.group(2) == "pm" or (not match.group(2) and hour < 8):
            hour += 12
        from_hour, to_hour, daypart = hour, 24, f"after {hour % 24}:00"

    food = any(word in joined for word in FOOD_WORDS)
    cats = _match_groups(tokens, CATEGORY_WORDS)
    depts = _match_groups(tokens, DEPT_WORDS)
    channels = _match_groups(tokens, CHANNEL_WORDS)

    # "som" maps to both a school and a source; the school is the useful read,
    # so don't also narrow the channel and hide SOM events on other calendars.
    if "som" in depts and "campus_groups" in channels:
        channels = [c for c in channels if c != "campus_groups"]

    claimed = {w for _s, words in CATEGORY_WORDS for w in words}
    claimed |= {w for _s, words in DEPT_WORDS for w in words}
    claimed |= {w for _s, words in CHANNEL_WORDS for w in words}
    claimed |= set(WEEKDAYS) | set(MONTHS) | STOPWORDS
    claimed |= {w for _n, words, _lo, _hi in DAYPARTS for w in words}
    claimed |= {w for phrase in FOOD_WORDS for w in phrase.split()}
    claimed |= {"today", "tomorrow", "tmrw", "weekend", "week", "month",
                "next", "days", "day", "after", "before"}
    claimed -= SPECIFIC
    keywords = [
        t for t in tokens
        if t not in claimed and len(t) > 2 and not t.isdigit()
    ]

    return Query(
        text=raw,
        start=start,
        end=end,
        span_label=span_label,
        from_hour=from_hour,
        to_hour=to_hour,
        daypart=daypart,
        cats=cats,
        depts=depts,
        channels=channels,
        keywords=keywords[:4],
        food=food,
    )


def _haystack(event: dict) -> str:
    return " ".join(
        [
            event.get("title") or "",
            event.get("description") or "",
            event.get("tags") or "",
            event.get("host") or "",
            event.get("location") or "",
        ]
    ).lower()


def search(query: Query, *, now: datetime | None = None) -> list[dict]:
    now = now or now_local()
    events = events_for_range(query.start.isoformat(), query.end.isoformat())
    enrich(events)

    out = []
    for event in events:
        if query.cats and event.get("category") not in query.cats:
            continue
        if query.depts and event.get("dept") not in query.depts:
            continue
        if query.channels and event.get("channel") not in query.channels:
            continue

        hay = _haystack(event)
        if query.food and not any(word in hay for word in FOOD_MATCH):
            continue
        if query.keywords and not all(word in hay for word in query.keywords):
            continue

        if event.get("all_day"):
            # An ongoing exhibition is a poor answer to "what's on tonight",
            # so a question about a specific stretch of the day wants only
            # events actually scheduled in it. Food is likewise served at a
            # time, not across a week-long exhibition.
            if query.from_hour is not None or query.food:
                continue
        else:
            start_dt = _start_of(event)
            if start_dt:
                # Don't offer events that already started today.
                if start_dt.date() == now.date() and start_dt < now:
                    continue
                if query.from_hour is not None:
                    if not (query.from_hour <= start_dt.hour < (query.to_hour or 24)):
                        continue
        out.append(event)

    # Chronological, but ongoing all-day listings sink below scheduled events:
    # only a handful of results are shown, and "what's on this weekend" should
    # not spend all of them on month-long exhibitions.
    out.sort(
        key=lambda e: (
            bool(e.get("all_day")),
            e.get("start") or "",
            e.get("title") or "",
        )
    )
    return _collapse(out)


def _collapse(events: list[dict]) -> list[dict]:
    """Drop repeat copies of one event.

    The shared dedupe in dedupe.py fingerprints on location, and the same
    event carries a different location string on each calendar it appears on
    ("Winslow Auditorium" vs "Sign in to download the location"), so copies
    survive into the feed. Collapse on title + start instead, preferring the
    copy that actually names a venue.

    A multi-day all-day event (a month-long exhibition) is stored as one row
    per day, so over a range it would otherwise crowd out everything else.
    Those collapse on title alone, keeping the earliest.
    """
    def usable_location(event: dict) -> int:
        location = (event.get("location") or "").lower()
        if not location:
            return 2
        return 1 if any(p in location for p in PLACEHOLDER_LOCATION) else 0

    best: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for event in events:
        key = (
            re.sub(r"\s+", " ", (event.get("title") or "").strip().lower()),
            "" if event.get("all_day") else (event.get("start") or "")[:16],
        )
        if key not in best:
            best[key] = event
            order.append(key)
        elif usable_location(event) < usable_location(best[key]):
            best[key] = event
    return [best[key] for key in order]


def _start_of(event: dict) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(event.get("start") or "")
    except ValueError:
        return None
    return parsed.astimezone(TZINFO) if parsed.tzinfo else parsed.replace(tzinfo=TZINFO)


def _when_label(event: dict, *, today: date) -> str:
    start_dt = _start_of(event)
    if not start_dt:
        return ""
    day = start_dt.date()
    if day == today:
        prefix = "Today"
    elif day == today + timedelta(days=1):
        prefix = "Tomorrow"
    else:
        prefix = start_dt.strftime("%a %b %-d")
    if event.get("all_day"):
        return f"{prefix} · all day"
    return f"{prefix} · {start_dt.strftime('%-I:%M %p')}"


def _describe_filters(query: Query) -> str:
    """Human-readable summary of what got filtered, for the reply line."""
    bits = []
    if query.food:
        bits.append("events likely to have food")
    for slug in query.cats:
        bits.append(LABELS.get(slug, slug).lower())
    for slug in query.depts:
        bits.append(_dept_label(slug))
    for slug in query.channels:
        bits.append(CHANNEL_LABELS.get(slug, slug))
    if query.keywords:
        bits.append("matching " + " + ".join(f"“{k}”" for k in query.keywords))
    if not bits:
        return "events"
    return ", ".join(bits)


def _dept_label(slug: str) -> str:
    from .facets import DEPARTMENTS

    for candidate, label, _needles in DEPARTMENTS:
        if candidate == slug:
            return label
    return slug


def _deep_link(query: Query) -> tuple[str, str]:
    """A URL into the existing filtered views, so chat hands off to the UI."""
    from urllib.parse import urlencode

    pairs: list[tuple[str, str]] = []
    for slug in query.channels:
        pairs.append(("channel", slug))
    for slug in query.depts:
        pairs.append(("dept", slug))
    for slug in query.cats:
        pairs.append(("cat", slug))
    if query.keywords:
        pairs.append(("q", query.keywords[0]))
    if query.from_hour is not None:
        pairs.append(("after", f"{query.from_hour:02d}:00"))
    else:
        pairs.append(("after", "all"))

    if query.start == query.end:
        pairs.insert(0, ("day", query.start.isoformat()))
        return "/?" + urlencode(pairs), "Open this day"
    pairs.insert(0, ("start", query.start.isoformat()))
    return "/week?" + urlencode(pairs), "Open the week view"


def _suggestions(query: Query) -> list[str]:
    """Narrower-to-broader nudges when a search comes back thin."""
    ideas = []
    if query.food:
        ideas.append("free food this week")
    if query.cats:
        ideas.append(f"{LABELS.get(query.cats[0], '').lower()} this week")
    if query.daypart:
        ideas.append(query.text.replace(query.daypart, "").strip() or "events this week")
    ideas.append("what's happening this weekend")
    ideas.append("talks next week")
    out = []
    for idea in ideas:
        idea = " ".join(idea.split())
        if idea and idea.lower() != query.text.lower() and idea not in out:
            out.append(idea)
    return out[:3]


TODAY_DAYPART = {
    "morning": "this morning",
    "afternoon": "this afternoon",
    "evening": "tonight",
    "lunchtime": "around lunchtime today",
}


def _window_label(query: Query) -> str:
    """Readable time window, with a preposition so replies scan as English.

    Avoids both "today morning" and "I found 3 events the next week".
    """
    if not query.daypart:
        label = query.span_label
    elif query.span_label == "today":
        label = TODAY_DAYPART.get(query.daypart, f"today, {query.daypart}")
    elif query.daypart in TODAY_DAYPART:
        label = f"{query.span_label}, in the {query.daypart}"
    else:
        label = f"{query.span_label}, {query.daypart}"

    first = label.split(",")[0].split()[0].lower() if label else ""
    if label.startswith("the ") or first in MONTHS:
        return f"in {label}"
    if first in WEEKDAYS:
        return f"on {label}"
    return label


@dataclass
class Answer:
    reply: str
    events: list[dict]
    more: int
    link: str
    link_label: str
    suggestions: list[str]
    query: Query


def answer(text: str, *, now: datetime | None = None) -> Answer:
    now = now or now_local()
    today = now.date()
    query = parse(text, today=today)
    found = search(query, now=now)

    window = _window_label(query)
    what = _describe_filters(query)
    count = len(found)

    if count:
        noun = "event" if count == 1 else "events"
        reply = f"I found {count} {noun} — {what} — {window}."
        if query.food:
            reply += (
                " Nothing in the data says “free,” so these are matches on"
                " food words in the listing."
            )
    else:
        reply = f"I couldn’t find {what} {window}."
        horizon = _last_loaded_day()
        if horizon and query.start > horizon:
            reply = (
                f"I don’t have listings that far out yet — the calendar currently"
                f" runs through {horizon.strftime('%B %-d')}. Try a closer date, or hit"
                f" Refresh on the day view to pull more."
            )
        elif (
            query.start == today
            and query.to_hour is not None
            and now.hour >= query.to_hour
        ):
            reply += " That part of the day has already passed — try tomorrow."

    link, link_label = _deep_link(query)
    for event in found[:MAX_RESULTS]:
        event["when_label"] = _when_label(event, today=today)

    return Answer(
        reply=reply,
        events=found[:MAX_RESULTS],
        more=max(0, count - MAX_RESULTS),
        link=link,
        link_label=link_label,
        suggestions=_suggestions(query) if count == 0 else [],
        query=query,
    )


def _last_loaded_day() -> date | None:
    """Newest event date in the database, to explain an empty far-future query."""
    from .db import connect

    con = connect()
    row = con.execute("SELECT max(substr(start, 1, 10)) FROM events").fetchone()
    con.close()
    if not row or not row[0]:
        return None
    try:
        return date.fromisoformat(row[0])
    except ValueError:
        return None
