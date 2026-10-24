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

## Genuine gaps — not covered

| Source | Why it is missing | Difficulty |
|---|---|---|
| Yale Law School | No Localist group; `law.yale.edu` has no public ICS | medium — needs HTML scraping |
| Yale Repertory Theatre | No Localist group; ticketing site, no feed found | medium |
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

## How to verify any of this yourself

```bash
.venv/bin/python -m yale_today login-check   # is the signed-in session live?
.venv/bin/python -m yale_today ingest --days 31
```

Then open the **Sources** tab, which reads the `source_runs` table: one row per
source per attempt, including failures, with counts and timestamps.
