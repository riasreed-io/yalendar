# Yalendar

One place to see what's happening at Yale and in New Haven, instead of checking five
calendars. Aggregates Yale Events (Localist), Yale Connect, SOM Campus Groups, Yale
Athletics, and New Haven community calendars into day, week, and month views.

Not an official Yale product. The internal package is still named `yale_today`.

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

The stable-host goal is `yalendar.fly.dev` (see `fly.toml`). Not yet deployed — it needs
`fly auth login` first:

```bash
fly auth login
fly secrets set SESSION_SECRET='long-random-string' YALE_TODAY_HTTPS=1
fly deploy
```

Do not upload the NetID PDF. After a scrape on the laptop, copy `data/events.db` to the
host or redeploy with the updated database.

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
