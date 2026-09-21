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

## Gotchas

- `httpx` must use `trust_env=False`; inherited proxy env vars cause 403s.
- Localist page size is 40, not 100 — the API returns 503 above that.
- Yale Connect (`yaleconnect.yale.edu`) and SOM Campus Groups (`groups.som.yale.edu`) are
  separate sources, not the same system.

See `HANDOFF.md` for full product intent, UX rules, and open work.
