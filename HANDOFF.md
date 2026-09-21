# Yalendar — full handoff for the next coder

Repo: `/Users/rias/Projects/yale-today`  
Product name: **Yalendar** (tab title and header). Internal package/folder still `yale_today`.  
Owner: Rias, Yale student. Audience: Yale students (friends + campus).  
Timezone: `America/New_York`.

This file is the source of truth for product intent, constraints, architecture, UX, and unfinished work. Prefer the code over older README lines that conflict (especially login).

---

## Paste this prompt into the new coder

```
You are taking over Yalendar, a FastAPI + Jinja + SQLite campus events dashboard for Yale students.

Repo: yale-today. Product name Yalendar. Package yale_today.

Read HANDOFF.md in the repo first, then the code. Do not invent CAS login, do not collect NetID/password on the website, do not commit secrets or the NetID PDF.

Current product:
- Aggregates public Yale calendars (events.yale.edu Localist), Yale Connect (yaleconnect.yale.edu), SOM Campus Groups (groups.som.yale.edu — separate from Connect), athletics ICS, New Haven community (NHFPL + UNH Localist).
- Day `/`, Week `/week`, Month `/calendar`. Title click → original listing. Dropdown chevron → description, chevron must stay absolutely positioned so open/close is the same click target.
- Filters: multi-select source/school/topic chips (OR within a row, AND across rows). Time: 1-hour slider 00:00–23:00 plus All times toggle. While dragging, show the hour live; apply filter on release. Default today: floor current hour. Default other days: all times. `after=now` only trims today's date.
- Open access: `_logged_in` in web.py currently always True. Do not put a NetID form on the site. Official Yale CAS for a student site requires ITS registration and a redirect, not an embed.
- Ingest: `python -m yale_today ingest --days 31`. Signed-in scrape: `--connect-login --headed` on Rias’s Mac with Duo; NetID PDF only at `/Users/rias/Downloads/Yale Calendar/Yale Net ID Info.pdf`. httpx must use trust_env=False (Cursor proxy 403). Localist pp=40 not 100 (503).
- Hosting: Cloudflare quick tunnels expire ~daily and change hostname. Goal stable host yalendar.fly.dev (fly.toml app=yalendar). Fly not logged in yet. After each UI update give a shareable URL if a tunnel is running.
- Design: Yale blue #00356b, gold #bd9b60, sand #f4efe4, Source Sans 3 + Source Serif 4. Desktop sidebar 270px + feed. Mobile: no giant white filter card; Date & search is a slim dropdown; chips and events first; viewport-fit; 16px inputs. Do not change desktop layout to “make mobile work.”
- Brand: header Yale (gold small caps) + Yalendar. Tab: `{date} · Yalendar`.

Continue from current code. Do not rewrite from scratch.
```

---

## What this product is

Yalendar is a **campus events dashboard**: one place to see what’s happening at Yale and nearby, without logging into five calendars.

It is **not** an official Yale product. It is **not** a CAS-authenticated student portal. Friends should be able to open a URL and use it.

Working name history: Yale Today → site is **Yalendar**. Fly app name `yalendar`.

### Jobs to be done

1. See today / this week / this month of campus events.
2. Filter by source (public Yale vs Connect vs SOM Campus Groups vs New Haven), school/department (SOM, YSE, Jackson, College, …), topic, org, and start time.
3. Click an event **title** and land on the original listing.
4. Expand a **description** without the UI jumping (fixed chevron).
5. Share a URL with friends (no invite code in the current live behavior).
6. Refresh ~one month of **public** data from the UI. Deeper Connect/SOM data needs a headed Duo scrape on Rias’s Mac.

---

## Hard constraints (do not violate)

1. **Never collect NetID or password on the website.** No login form for Yale credentials. No iframe/embed of official CAS. Yale ITS CAS for a student app is a **redirect after registration**, not an embed.
2. **Never commit** NetID, passwords, `data/dashboard_password.txt`, `events.db`, `.env`, or the NetID PDF. PDF path only: `/Users/rias/Downloads/Yale Calendar/Yale Net ID Info.pdf`. Credentials are parsed in memory via `credentials.py` and discarded.
3. **Campus Groups ≠ Yale Connect.**  
   - Yale Connect: `yaleconnect.yale.edu`  
   - SOM Campus Groups: `groups.som.yale.edu`  
   Treat as separate sources/channels. Gold = Campus Groups (SOM). Blue = Connect. Tan = public Yale. Green = New Haven.
4. **httpx `trust_env=False`.** Cursor/proxy env vars cause 403 if you inherit `HTTP_PROXY`.
5. **Localist page size 40**, not 100 (API 503).
6. **Playwright Duo scrape must be headed**, often from Terminal.app not a headless Cursor agent (hangs / no Duo buzz).
7. **Cloudflare quick tunnels** (`*.trycloudflare.com`) expire (~24h) and get a **new random hostname** every restart. Old bookmarks 1033. This is not a mobile CSS bug.
8. Desktop layout stays a **270px sidebar + feed**. Mobile must fit iPhone without redesigning desktop.

---

## Current live behavior vs README

README still mentions `@yale.edu` email + shared password. **The running app does not gate access.**

```python
# yale_today/web.py
def _logged_in(request: Request) -> bool:
    return True
```

Invite code **Bulldog** exists in `config.SHARED_INVITE` and `db.invites`, and `/login` still exists, but nothing redirects there while `_logged_in` is True.

If you restore a gate, product history was: invite-only “Bulldog”, then open calendar. Owner’s last intent: **open access**, no email/invite for friends.

`/refresh` does **public** ingest only (`include_connect_login=False`, `days=WINDOW_DAYS` = 31). It does not run Duo.

---

## Stack

| Piece | Choice |
|---|---|
| Language | Python 3.12+ (local .venv has 3.14) |
| Web | FastAPI + Jinja2 + Starlette sessions |
| DB | SQLite `data/events.db` WAL |
| Templates | `yale_today/templates/` |
| CSS | `yale_today/static/style.css` (cache-bust `?v=filter7`) |
| HTTP | httpx, certifi, `trust_env=False` |
| HTML parse | BeautifulSoup + lxml |
| Calendars | icalendar |
| Login scrape | Playwright Chromium, headed |
| Serve | uvicorn `python -m yale_today serve --host 0.0.0.0 --port 8002` |
| Deploy (planned) | Fly.io Dockerfile, `fly.toml` app `yalendar`, region `ewr` |

No frontend framework. No React. No tests directory.

---

## Run locally

```bash
cd ~/Projects/yale-today   # or wherever the clone lives
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python -m yale_today ingest --days 31
python -m yale_today serve --host 0.0.0.0 --port 8002
```

Monthly / signed-in scrape (Rias Mac, Duo in a visible Chrome window):

```bash
python -m yale_today ingest --days 31 --connect-login --headed
# or a calendar month:
python -m yale_today ingest --month 2026-09 --connect-login --headed
```

Share (while Mac + processes run):

```bash
.tools/cloudflared tunnel --url http://127.0.0.1:8002 --no-autoupdate
```

`.tools/cloudflared` is gitignored. Quick tunnel hostname is random. Uvicorn has **no auto-reload** unless `YALE_TODAY_RELOAD=1`. After Python changes, restart the process (SIGTERM 143 on the old pid is expected).

---

## Repository map

```
yale_today/
  __main__.py          CLI: ingest | serve
  config.py            paths, TZ, WINDOW_DAYS=31, SHARED_INVITE
  web.py               FastAPI routes, filters, time slider, templates
  db.py                SQLite schema, upsert, feeds, invites
  models.py            Event dataclass, ids, fingerprint
  ingest.py            orchestrates all sources
  localist.py          events.yale.edu API /api/2/events
  connect.py           CampusGroups mobile_ws for Connect + SOM
  connect_login.py     Playwright CAS + Duo, 10 min wait
  credentials.py       read NetID PDF in memory only
  community.py         NHFPL + University of New Haven Localist
  ics_feeds.py         athletics ICS + extra URLs
  http.py              httpx client
  facets.py            channels, depts, enrich, apply_filters, filter_by_time
  categories.py        topic classification
  dedupe.py            near-duplicate grouping, events_for_day/range
  auth.py              dashboard password file (unused while open access)
  templates/           Jinja
  static/style.css
data/                  gitignored db, password, connect json
fly.toml / Dockerfile
HANDOFF.md             this file
```

---

## Data model

`events` table: `id`, `source`, `source_id`, `title`, `start`, `end`, `all_day`, `location`, `description`, `url`, `host`, `tags`, `fingerprint`, `canonical_id`, `extra_json`.

Sources (DB `source` field):

| source | channel (UI) | color |
|---|---|---|
| localist | public | tan `#8a6d3b` |
| athletics | public | tan |
| ics | public | tan |
| yale_connect | yale_connect | blue `#286dc0` |
| campus_groups | campus_groups | gold |
| nhfpl, unh | community | green `#3d7a55` |

`feeds` table: extra ICS URLs from `/settings`.  
`invites` / `visitors`: leftover from invite-wall.

Dedupe: fingerprint on title + start minute + location; keep earliest source by rank.

---

## Ingest pipeline

`run_ingest()`:

1. Optional Playwright login (Connect then SOM), capture `mobile_events_list` JSON + ICS URLs.
2. Localist `https://events.yale.edu/api/2/events` pagesize 40.
3. Public Connect `https://yaleconnect.yale.edu/mobile_ws/v17/mobile_events_list`.
4. Public SOM `groups.som.yale.edu` same mobile_ws pattern (`SOM_LIST` / `SOM_ORIGIN` in connect.py).
5. Community: NH Free Public Library + UNH Localist.
6. Athletics ICS `https://yalebulldogs.com/calendar.ashx/calendar.ics`.
7. Extra ICS from `connect_feeds.json` and `feeds` table.
8. Upsert SQLite. Window: `--month YYYY-MM` or `--days N` from today.

Public SOM scrape has produced ~100 September events historically. Signed-in scrape adds private/campus-only listings after Duo.

Playwright: fill CAS from PDF; wait up to ~10 minutes for Duo; platforms listed in `connect_login.PLATFORMS`. Must be `--headed`.

---

## Routes

| Method | Path | Role |
|---|---|---|
| GET | `/` | Day list |
| GET | `/week` | Week planner (Sunday start) |
| GET | `/calendar` | Month grid |
| GET | `/settings` | Extra ICS feeds |
| POST | `/settings` | Save feed URLs |
| POST | `/refresh` | Public 31-day ingest |
| GET/POST | `/login` `/logout` | Unused while `_logged_in` True |
| GET | `/friends` | Invite leftover page |
| static | `/static/style.css` | CSS |

Query params (repeatable lists): `channel`, `dept`, `cat`. Also `org`, `q`, `sort`, `group`, `day`/`start`/`month`/`cal`, `after`.

`after`:

- `all` — whole day(s)
- `now` — drop timed events **today** that already started; other dates kept; all-day kept
- `HH:00` — keep events with local start ≥ that clock (all-day kept). On week/month this applies to **every** day in the view
- integer `0–23` — hour step from the slider

Default: **today** → floor current hour as `HH:00`. Other day views → `all`. Week/month default `now`.

---

## Filters (product rules)

**In unison:** sources, schools, topics are independent multi-selects.

- Within a row: OR (Connect **or** Campus Groups).
- Across rows: AND (those sources **and** SOM **and** talks).
- Click a selected chip again to remove it.
- **All** on a row clears that facet.
- Facet counts are computed on the **unfiltered** window (so chips don’t vanish).

**Time:**

- Range input 0–23, one hour per step.
- Tick labels every 4 hours: 12 am, 4 am, 8 am, 12 pm, 4 pm, 8 pm (not noon/5pm/8pm as special product names).
- **All times** chip separate from the slider.
- `oninput` → live “From 7:00 PM” + bubble above thumb (`yalendarTimePreview` in `base.html`).
- `onchange` → navigate (`yalendarTimeGo`).
- Dragging undims the slider if All times was on (until navigation).

**Org / sort / group:** sidebar selects. Group by source, category, department, org, or one list. Day view only.

---

## UX / design system

**Brand**

- Tab: `{2026-09-20} · Yalendar` / `{week} · Yalendar` / `{September 2026} · Yalendar`
- Header: gold small-caps **YALE** + large **Yalendar**
- Subtitle: “Campus events for Yale students” (hidden on mobile)
- Fonts: Source Sans 3, Source Serif 4 (Google Fonts)
- Colors: `--yale-blue #00356b`, `--yale-mid #286dc0`, `--yale-gold #bd9b60`, `--yale-sand #f4efe4`

**Event interaction (strict)**

- Title is a link to `event.url` (new tab).
- Chevron is `<details class="expand">` with **icon-only** summary.
- CSS: `.event-head { position: relative; padding-right: 2.6rem }` and `summary { position: absolute; top: 0; right: 0 }`.
- Do **not** `flex: 1 1 100%` on open details (that moved the icon).
- Same pattern on week items and month titles (`.month-event`).

**Desktop**

- `.layout` grid `270px minmax(0,1fr)`
- Sticky white filter card (date, mini-month, search, org, sort, group)
- Feed: time slider + chips + events

**Mobile (max-width 860px)**

- Single column. **Do not** show a large empty white Filters box on first paint.
- Sidebar form inside `.filter-panel`, hidden until **Date & search ▾**.
- `.filters` transparent, no card chrome when collapsed.
- Feed order in DOM is still aside then feed; collapsed aside is a one-line control then date + chips + events.
- Header wraps; hide brand subtitle; `viewport-fit=cover`; inputs 16px (no iOS zoom).
- Month grid stays 7 columns, compressed. Week stacks to 1 column.
- `overflow-x: hidden` on html/body.

Mini-month: today highlighted light blue (`#d4e6f7`). Day/week views include mini calendar.

---

## Template notes

- `_chips.html` — time slider + source/dept/topic chips (shared day/week/month)
- `_filter_hiddens.html` — preserve channel/dept/cat/after on GET forms
- `_event_expand.html` — title + description details
- `_mini_month.html` — day/week sidebar
- `base.html` — chrome, CSS `?v=filter7`, slider JS
- Cache-bust CSS whenever you change `style.css`

Jinja `href(**overrides)` and `toggle(key, slug)` from `_filter_href` in `web.py`. Lists encoded as repeated query keys (`channel=a&channel=b`).

---

## Hosting / share URLs

**Today:** Cloudflare **quick** tunnel. Hostname like `https://something.trycloudflare.com`. Expires ~daily, 1033 if dead. New link after each tunnel restart.

**Goal:** `https://yalendar.fly.dev` via `fly.toml`. Not deployed: `flyctl auth whoami` had no token. After `fly auth login`:

```bash
fly secrets set YALE_TODAY_PASSWORD='...' SESSION_SECRET='...' YALE_TODAY_HTTPS=1
fly deploy
```

Copy `data/events.db` to the host after Mac ingest. Do not upload the NetID PDF. `auto_stop_machines = "stop"` and `min_machines_running = 0` will sleep the VM — consider `min_machines_running = 1` if cold starts annoy friends.

Owner asked for named URL because quick-tunnel names cannot be customized.

---

## Known issues / follow-ups

1. **Stable hosting** — Fly login + deploy; tunnel is a stopgap.
2. **README out of date** — still describes email/password gate.
3. **No tests.**
4. **Uvicorn no reload** — restart after Python edits.
5. **`after=HH:00` on week/month** filters every day, not only today (`now` only trims today). Confirm with Rias if that’s desired.
6. **Invite/login/friends pages** leftover.
7. **Connect/SOM signed-in data** depends on Duo on Rias’s machine; public scrape is what Refresh uses.
8. **Localist 503** if page size too high.
9. **Proxy 403** if httpx uses env proxies.
10. **Old trycloudflare bookmarks always 1033** — not a frontend bug.
11. **config.DEFAULT_NETID_PDF** is a machine-specific absolute path.

---

## Product decisions already made (don’t relitigate unless asked)

- Name: Yalendar, not Yale Today / YaleCalendar in the UI.
- Open access (no Bulldog wall in current code path).
- Title → source URL; chevron → description; chevron must not move.
- Multi-select filters, click to add/remove.
- Time is a **1-hour slider** + **All times**, live preview while dragging.
- Campus Groups (SOM) is its own channel, gold.
- No CAS embed.
- Share URL after user-facing updates when a tunnel is up.

---

## Sample user prompts from this build (history)

Paraphrased, in order of evolution:

1. Host a dashboard of Yale + Campus Groups + classification; monthly snapshot; share with friends; no NetID on the site.
2. Need September / Campus Groups visible.
3. Week tab + month tab + mini calendar; clearer today highlight.
4. Expand description; title is the source link; bigger fixed dropdown.
5. Tab title Yalendar (can’t customize tunnel hostname).
6. Multi-select filters; click again to remove; mobile must fit iPhone; keep desktop layout.
7. Don’t open on a large white filter box; slim dropdown; land on chips/events.
8. Hide earlier-today events (e.g. 6pm). Then slider: 30 min, then 1 hour; forget noon/5/8 as unique stops; regular ticks. Live time while dragging.
9. New share link when tunnel expires; they expire about daily.

If the new coder is asked for a shareable URL: start uvicorn on 8002, start cloudflared, paste the **new** hostname. Never tell people to reuse a dead `*.trycloudflare.com` link.
