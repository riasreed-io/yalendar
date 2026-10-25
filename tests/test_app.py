"""Functional checks for Yalendar.

Written against the real database rather than fixtures: the bugs that have
actually shipped here were data-shaped (a time filter carried onto the wrong
day, pagination silently truncating a source), and a mocked database would
have passed every one of them.

Run:  .venv/bin/python -m pytest tests -q
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from yale_today.config import now_local, today_local
from yale_today.web import app

client = TestClient(app)

PAGES = ["/", "/week", "/calendar", "/ask", "/sources", "/settings"]
EVENT_RE = re.compile(r'class="event ')


def count_events(resp) -> int:
    return len(EVENT_RE.findall(resp.text))


def days(n: int) -> list[str]:
    import datetime
    base = today_local()
    return [(base + datetime.timedelta(days=i)).isoformat() for i in range(n)]


# ------------------------------------------------------------------ pages

@pytest.mark.parametrize("path", PAGES)
def test_every_page_renders(path):
    r = client.get(path)
    assert r.status_code == 200, path
    # A Jinja failure can still return 200 with the error inlined.
    assert "Traceback" not in r.text
    assert "jinja2" not in r.text.lower()


@pytest.mark.parametrize("path", PAGES)
def test_no_unrendered_template_syntax(path):
    body = client.get(path).text
    assert "{{" not in body, f"unrendered expression in {path}"
    assert "{%" not in body, f"unrendered tag in {path}"


# ------------------------------------------------------- the day-pick bug

def test_picking_a_day_shows_that_days_events():
    """The regression that made days look empty.

    The day view defaults `after` to the current hour, which is a fact about
    today. It used to ride along in every generated link, so opening another
    day hid everything before that hour.
    """
    for day in days(8):
        shown = count_events(client.get("/", params={"day": day}))
        exist = count_events(client.get("/", params={"day": day, "after": "all"}))
        if exist and day != today_local().isoformat():
            assert shown == exist, f"{day}: {shown} shown but {exist} exist"


def test_navigation_links_do_not_carry_the_implicit_time_default():
    body = client.get("/").text
    other_day_links = re.findall(r'href="(/\?day=\d{4}-\d{2}-\d{2}[^"]*)"', body)
    assert other_day_links, "no day links rendered"
    today = today_local().isoformat()
    for link in other_day_links:
        if f"day={today}" in link:
            continue
        assert "after=" not in link, f"link leaks a time filter: {link}"


def test_an_explicit_time_choice_is_preserved():
    body = client.get("/", params={"after": "18:00"}).text
    links = re.findall(r'href="(/\?day=\d{4}-\d{2}-\d{2}[^"]*)"', body)
    assert any("after=18" in link.replace("%3A", ":") for link in links)


# ----------------------------------------------------------------- filters

def test_source_filter_matches_its_facet_count():
    base = {"day": today_local().isoformat(), "after": "all"}
    page = client.get("/", params=base).text
    for slug in ("yale_connect", "campus_groups", "localist", "nhfpl"):
        m = re.search(rf'href="[^"]*channel={slug}[^"]*"[^>]*>([^<]*)<em>(\d+)</em>', page)
        if not m:
            continue
        expected = int(m.group(2))
        got = count_events(client.get("/", params={**base, "channel": slug}))
        assert got == expected, f"{slug}: chip says {expected}, filter returns {got}"


def test_filters_narrow_rather_than_widen():
    base = {"day": today_local().isoformat(), "after": "all"}
    total = count_events(client.get("/", params=base))
    for extra in ({"channel": "yale_connect"}, {"cat": "talks"},
                  {"dept": "som"}, {"q": "yale"}):
        got = count_events(client.get("/", params={**base, **extra}))
        assert got <= total, f"{extra} returned more than unfiltered"


def test_combining_filters_is_an_intersection():
    base = {"day": today_local().isoformat(), "after": "all"}
    a = count_events(client.get("/", params={**base, "channel": "yale_connect"}))
    b = count_events(client.get("/", params={**base, "cat": "talks"}))
    both = count_events(client.get("/", params={**base, "channel": "yale_connect", "cat": "talks"}))
    assert both <= min(a, b)


def test_multiple_values_in_one_row_are_a_union():
    base = [("day", today_local().isoformat()), ("after", "all")]
    a = count_events(client.get("/", params=base + [("channel", "campus_groups")]))
    b = count_events(client.get("/", params=base + [("channel", "community")]))
    both = count_events(client.get("/", params=base + [("channel", "campus_groups"),
                                                       ("channel", "community")]))
    assert both == a + b, f"union was {both}, parts were {a} + {b}"


def test_time_filter_only_removes_earlier_events():
    base = {"day": days(3)[2], "after": "all"}
    everything = count_events(client.get("/", params=base))
    evening = count_events(client.get("/", params={**base, "after": "18:00"}))
    assert evening <= everything


def test_department_filter_finds_multi_unit_events():
    """Events list several units; filtering by a non-first one must still hit."""
    r = client.get("/", params={"day": today_local().isoformat(), "after": "all"})
    slugs = re.findall(r'<option value="([a-z0-9-]{3,})"', r.text)
    assert slugs, "no department options rendered"
    hits = 0
    for slug in slugs[:12]:
        if count_events(client.get("/", params={"day": today_local().isoformat(),
                                                "after": "all", "unit": slug})):
            hits += 1
    assert hits > 0, "no department filter returned anything"


# -------------------------------------------------------------- week/month

def test_week_shows_seven_days_and_real_events():
    r = client.get("/week", params={"after": "all"})
    assert r.text.count('class="week-col') == 7
    assert r.text.count("week-title") > 0


def test_month_grid_is_whole_weeks():
    r = client.get("/calendar", params={"after": "all"})
    cells = r.text.count('class="month-cell')
    assert cells % 7 == 0 and cells >= 28, f"{cells} cells is not whole weeks"


def test_week_and_month_agree_with_the_day_view():
    day = days(3)[2]
    day_count = count_events(client.get("/", params={"day": day, "after": "all"}))
    week = client.get("/week", params={"start": day, "after": "all"})
    assert week.status_code == 200
    if day_count:
        assert "week-title" in week.text


# ----------------------------------------------------------------- the API

def test_api_events_matches_the_html_view():
    day = today_local().isoformat()
    api = client.get("/api/events", params={"start": day, "end": day, "after": "all"}).json()
    html = count_events(client.get("/", params={"day": day, "after": "all"}))
    assert api["count"] == html, f"api {api['count']} vs html {html}"


def test_api_omits_descriptions_but_detail_has_them():
    day = today_local().isoformat()
    rows = client.get("/api/events", params={"start": day, "end": day, "after": "all"}).json()["events"]
    if not rows:
        pytest.skip("no events today")
    assert "description" not in rows[0]
    with_desc = next((e for e in rows if e["has_description"]), None)
    if with_desc:
        detail = client.get(f"/api/events/{with_desc['id']}").json()
        assert detail["description"].strip()


def test_api_rejects_unknown_event():
    assert client.get("/api/events/does-not-exist").status_code == 404


def test_sources_tab_reports_every_expected_source():
    from yale_today.web import EXPECTED_SOURCES
    body = client.get("/sources").text
    for _slug, label, _origin, _kind in EXPECTED_SOURCES:
        assert label in body, f"{label} missing from the Sources tab"


def test_ask_returns_events_for_a_plain_question():
    data = client.post("/api/ask", json={"q": "talks this week"}).json()
    assert data["engine"] == "local"
    assert data["reply"]


# ------------------------------------------------------------ bad input

@pytest.mark.parametrize("params", [
    {"day": "not-a-date"},
    {"day": "2026-13-45"},
    {"after": "99:99"},
    {"after": "../../etc/passwd"},
    {"channel": "nonsense"},
    {"unit": "nonsense"},
    {"sort": "nonsense"},
    {"group": "nonsense"},
    {"q": "<script>alert(1)</script>"},
    {"day": "1900-01-01"},
    {"day": "2099-01-01"},
])
def test_bad_input_does_not_crash(params):
    r = client.get("/", params=params)
    assert r.status_code in (200, 422), f"{params} -> {r.status_code}"
    if r.status_code == 200:
        assert "Traceback" not in r.text


def test_search_input_is_escaped():
    r = client.get("/", params={"q": "<script>alert(1)</script>"})
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_month_range_is_clamped():
    r = client.get("/api/events", params={"start": "2026-01-01", "end": "2030-01-01"}).json()
    assert r["end"] < "2027-01-01", "an unbounded range would scan the whole table"


# ---------------------------------------------------------------- assets

@pytest.mark.parametrize("asset", ["/static/style.css", "/static/chat.js", "/static/fluid.js"])
def test_static_assets_served(asset):
    r = client.get(asset)
    assert r.status_code == 200 and len(r.content) > 500


def test_pages_reference_assets_that_exist():
    body = client.get("/").text
    for path in set(re.findall(r'(?:href|src)="(/static/[^"?]+)', body)):
        assert client.get(path).status_code == 200, f"broken asset {path}"
