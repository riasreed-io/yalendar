# Event source coverage checklist

What Yalendar pulls, what it deliberately does not, and what is still missing.
Every claim here was checked against the live services on 2026-10-24, not
assumed. The live version of the top table is the **Sources** tab on the site,
which shows the real pull counts and timestamps.

## Covered now

| # | Source | Origin | Access | Status |
|---|---|---|---|---|
| 1 | Yale Events (Localist) | `events.yale.edu/api/2/events` | public API | covered |
| 2 | Yale Connect | `yaleconnect.yale.edu` mobile_ws | public **+ signed in** | covered |
| 3 | SOM Campus Groups | `groups.som.yale.edu` mobile_ws | public **+ signed in** | covered |
| 4 | Yale Athletics | `yalebulldogs.com` ICS | public ICS | covered |
| 5 | New Haven Free Public Library | `nhfpl.libcal.com` | public | covered |
| 6 | University of New Haven | UNH Localist | public | covered |
| 7 | Extra ICS feeds | user-supplied, Feeds tab | public ICS | covered |

Signing in matters and is measurable. Anonymous vs authenticated, same endpoint:

| Platform | anonymous | signed in |
|---|---|---|
| Yale Connect | 32 rows, 23 venues hidden | 35 rows, 1 hidden |
| SOM Campus Groups | 51 rows, 6 hidden | 58 rows, 5 hidden |

Those listings only release their venue to an authenticated session, so the
drop in hidden venues is proof the sign-in is real.

## Already covered *through* Localist — no separate feed needed

`events.yale.edu` aggregates **186 Yale groups**, confirmed by paging its
`/api/2/groups` endpoint. These each have a Localist group, so they arrive
already and do not need their own scraper:

- Yale Peabody Museum
- Yale Center for British Art
- Yale School of Music, Institute of Sacred Music
- Yale Divinity School, Berkeley Divinity School
- Yale University Art Gallery, Schwarzman Center, Beinecke, Yale Library
- The cultural centers (Afro-American, Asian American, La Casa, Native)

Low event counts for some of these mean the venue posts little in the current
window, not that the source is missing.

## Corrected: these are NOT gaps

An earlier version of this file listed Yale Law School and Yale Repertory
Theatre as missing. Both are covered, via **Yale Connect** rather than
Localist — Yale Rep 107 events, Law School 54. Checking only Localist was
the mistake.

## Genuine gaps — not covered

| Source | Why it is missing | Difficulty |
|---|---|---|
| City of New Haven events | `newhavenct.gov` returns 403 to scripted requests | medium — needs a real browser |
| Music venues (College St, Toad's) | Commercial ticketing, no open feed | low value, high effort |
| Residential college calendars | Behind NetID per-college, not one feed | hard |

Ten candidate ICS URLs were probed directly; all returned 404, which proves
the guessed paths were wrong rather than that no feed exists. Finding the real
ones needs per-site discovery.

## Not pulled on purpose

- **Yale email / Canvas / personal calendars.** Out of scope; Yalendar is a
  public listing aggregator, not a personal calendar client.
- **Anything requiring NetID beyond Connect/Campus Groups.** No credential is
  collected on the website, ever.

## Per-department filtering

Every unit an event belongs to is indexed, not just the first. Localist
returns multiple groups per event ("Yale Arts, Yale University Art
Gallery"); keeping only the first hid 1,161 events from the units further
down their own list. **361 departments** are individually filterable from the
sidebar, with live counts.

## Fetching is only as good as its pagination

Localist reports `page.total` inconsistently — 6 pages on one call and 22
minutes later for the identical query, which silently ingested a third of
the calendar with no error raised. The fetcher no longer trusts that field
and pages until a short page arrives; three consecutive runs now return 848,
848, 848. The Sources tab is what made this visible.

Per-group fetching (one request per department) was built and measured
against this: 804 events in 152s versus 848 in 41s from the main feed. It
found nothing extra, so it is available but deliberately not part of the
default ingest.

## How to verify any of this yourself

```bash
.venv/bin/python -m yale_today login-check   # is the signed-in session live?
.venv/bin/python -m yale_today ingest --days 31
```

Then open the **Sources** tab, which reads the `source_runs` table: one row per
source per attempt, including failures, with counts and timestamps.
