# Yalendar

One place to see what's happening at Yale and in New Haven, instead of checking five
calendars. Aggregates Yale Events (Localist), Yale Connect, SOM Campus Groups, Yale
Athletics, and New Haven community calendars into day, week, and month views.

Not an official Yale product. The internal package is still named `yale_today`.

## Live app

**https://yalendar.onrender.com** — free hosting, so the first request after
a quiet spell takes ~50 seconds to wake. Everything works there with no
account.

## Or run it from a fresh clone, in about two minutes

The repository ships a frozen, public-only snapshot of **2,802 real events
across 9 sources**, so this needs no Yale login, no API key and no network.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
YALENDAR_MODE=demo python -m yale_today serve
```

Open <http://127.0.0.1:8000/>. The clock is pinned to the day the snapshot was
taken, so every view is populated; a banner on every page says which day that is.

**To enable the AI assistant**, put `PORTKEY_API_KEY=...` in a `.env` file
either in this folder or **one folder above it** — both are checked, in that
order. `OPENAI_API_KEY` works too. Without either, Ask falls back to a free
keyword search and says so on screen.

```bash
YALENDAR_MODE=demo python -m yale_today serve     # same command; the key is picked up automatically
```

Signing into Yale Connect / Campus Groups is optional, personal-machine-only,
and needs two extra packages: `pip install -r requirements-signin.txt`.

## Three builds, one codebase

Yalendar began as one person's local tool: one SQLite file, one saved Yale
sign-in. Sharing it meant naming that assumption instead of relying on it, so
`YALENDAR_MODE` selects which build is running and every path that touches the
network, the disk or a credential checks it (`yale_today/config.py`).

| mode | database | fetches | writes | can sign in | who it is for |
|---|---|---|---|---|---|
| `personal` *(default)* | `data/events.db` | yes | yes | yes | you, on your own machine |
| `demo` | rebuilt from `demo/snapshot.json.gz` | no | no | no | strangers, graders, the public link |
| `public` | `data/events.db` | yes | yes | **no** | a live deployment of the public sources |

```bash
python -m yale_today mode     # what this build is and what it may do
```

### The demo build

```bash
YALENDAR_MODE=demo python -m yale_today serve
```

Serves `demo/snapshot.json.gz` — 2,800+ events across 9 sources, committed to the
repo. No Yale account, no API key, no network. Two things make it usable rather
than merely safe:

- **The clock is pinned to the snapshot date.** A frozen calendar against a
  moving clock empties out within a week and looks broken. Every view stays
  populated, and a banner on every page says which day you are looking at.
- **It is public by construction, not by filtering.** `scripts/make_demo.py
  --rebuild` ingests into a throwaway directory with `YALENDAR_MODE=public`,
  which disables every signed-in source *in code*. Nothing private can enter it,
  and `demo.export()` refuses outright to snapshot a database holding
  authenticated pulls.

```bash
python scripts/make_demo.py --rebuild    # refresh it (a few minutes)
python scripts/make_demo.py --inspect    # what is in the current one
```

### Someone else using it with their own account

```bash
python -m yale_today setup
```

Pulls the public calendars first — that alone is most of the app and needs no
account — then *offers* the Yale sign-in. See "Access" below for what that
sign-in does and does not do. Personal iCal feeds go in on the `/connect` page.

Multi-tenant hosting (several people's private events on one server) is **not**
implemented and is not planned: it would mean storing other people's Yale
sessions on a machine I control. The supported answers are the demo build, a
public-sources deployment, or running your own copy.

## Access

The site is open — no login, no invite code. Anyone with the URL can view it.

**NetID and password are never collected on the website, ever.** There is no Yale
credential form and no embedded CAS. (Official Yale CAS for a student site requires ITS
registration and a redirect, not an embed.) Signed-in scrapes of Yale Connect and Campus
Groups run on Rias's Mac with Duo, roughly monthly; everyone else views the stored
snapshot. Credentials are read into memory from a local PDF and discarded — never stored
in the app, the database, or the repo.

`/login`, `/friends`, and the `Bulldog` invite code are leftovers from an earlier
invite-only version. Nothing routes to them while access is open.

### What signing in actually does

There is no credential field anywhere in this app, in any mode. `python -m
yale_today login` (or the button on `/connect`) opens a real Chrome window on
*your* machine pointed at Yale's own CAS page; you type there, Duo goes to your
phone, and the only thing kept is a session cookie in `data/session_state.json`
on your disk. Yalendar never reads, types or transmits a NetID.

Signing in buys two things: Yale Connect and SOM Campus Groups blank the venue
for logged-out visitors ("Sign in to download the location"), and they hide
club events restricted to members.

The `demo` and `public` builds **refuse** to sign in — `session_login` raises
rather than trusting that nobody will run the command.

## Local

```bash
cd ~/Projects/yale-today
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python -m yale_today ingest --days 31
python -m yale_today serve --host 0.0.0.0 --port 8002
```

Uvicorn does not auto-reload unless `YALE_TODAY_RELOAD=1`, so restart the process after
editing Python.

### Signed-in scrape (Rias's Mac only)

Needs a visible browser window to approve Duo:

```bash
python -m yale_today ingest --days 31 --connect-login --headed
```

Often has to be run from Terminal.app rather than an editor's agent shell, which can hang
without ever sending the Duo push. The `/refresh` button in the UI runs the **public**
ingest only; it never triggers Duo.

## Sharing

Cloudflare quick tunnels expire after about a day and get a new random hostname each
restart, so old links return error 1033:

```bash
.tools/cloudflared tunnel --url http://127.0.0.1:8002 --no-autoupdate
```

**Deployed at https://yalendar.onrender.com** — the demo build, from
`render.yaml`. Free instance, so it sleeps after 15 minutes idle and the next
request waits ~50s. Pushing to `main` redeploys it.

`fly.toml` is kept for a Fly deploy, but Fly no longer has a free tier: new
accounts get 2 hours of machine runtime or 7 days, then need a card.

`data/` is excluded from the image wholesale, not file by file. It holds the
saved Yale session *and* `events.db`, which contains members-only club events
that are in it only because somebody signed in. The image gets
`demo/snapshot.json.gz` and rebuilds its database from that at startup, so
there is nothing private for it to serve and nothing stale to leave on a volume.
Never upload the NetID PDF.

## Agent + React frontend

Added alongside the Jinja app, which still works on its own. Nothing was removed.

```
yale_today/agent/     models.py, tools.py, agent.py  (pydantic-ai)
yale_today/api.py     JSON API for the frontend, CORS-enabled
prompts/prompt.md     system prompt, loaded at runtime
output/audit_trail.json   append-only log of agent runs (gitignored)
frontend/             Vite + React 19 + TypeScript, lint via oxlint
```

Run the backend and the frontend in two terminals:

```bash
.venv/bin/python -m yale_today serve --host 127.0.0.1 --port 8002
```

```bash
cd frontend && npm run dev
```

The frontend reads `VITE_API_BASE` (default `http://127.0.0.1:8002`). Verify
without starting anything:

```bash
.venv/bin/python -c "import yale_today.web, yale_today.agent.agent"
cd frontend && npx tsc -b && npx oxlint
```

### Two spend ceilings, not one

`agent/agent.py` caps a single question at 6 requests, 6 tool calls, 40k tokens
and $0.25. That stops a runaway loop inside one run and does nothing about ten
thousand runs. `agent/budget.py` is the second ceiling: every answered question
is logged to `data/agent_usage.db` with its measured cost, and three limits are
checked before the model is built — questions per day, dollars per day, and
questions per hour from one caller. Over the line the question is still
answered, by the free local search; a budget cap that returns an error page is
an outage.

Honest limitation: the counter is per machine, so several machines get that
multiple of the ceiling and a restart begins the day's count again.

### The agent is off for visitors by default

The site is open to anyone with the URL, so a model-backed endpoint would bill
every stranger's question to you. `/api/agent` therefore only runs the model for
local requests; everyone else transparently gets the free local search, which
needs no key. Set `YALENDAR_PUBLIC_AGENT=1` to open it to all visitors — do that
only with rate limiting and a spend cap in place.

Copy `.env.example` to `.env` and set `OPENAI_API_KEY` to enable the agent at
all. Without it, Ask silently falls back to the local search.

## Gotchas

- `httpx` must use `trust_env=False`; inherited proxy env vars cause 403s.
- Localist page size is 40, not 100 — the API returns 503 above that.
- Yale Connect (`yaleconnect.yale.edu`) and SOM Campus Groups (`groups.som.yale.edu`) are
  separate sources, not the same system.

See `HANDOFF.md` for full product intent, UX rules, and open work.
