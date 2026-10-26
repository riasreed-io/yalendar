FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY yale_today ./yale_today
# The agent reads its system prompt from disk at runtime; without this the
# image builds fine and then raises FileNotFoundError on the first question.
COPY prompts ./prompts
# The only events data in the image: the committed public-only snapshot.
# data/ is NOT copied. It holds the personal database -- which contains
# members-only club events pulled with a Yale sign-in -- plus the session
# cookies themselves. The deployed build rebuilds its database from this
# snapshot at startup, so there is nothing private for it to serve.
COPY demo ./demo

# Frozen snapshot, no network, no sign-in, no writes. Overriding this to
# "public" gives a live public-sources build instead; "personal" is for
# your own machine and is refused the moment it would need a session.
ENV YALENDAR_MODE=demo
# Ceilings travel with the image, not with one host's config file. fly.toml
# repeats them, but Render, Railway and anywhere else read nothing but this
# -- and an image whose spend limits depend on remembering to set five
# environment variables is an image with no spend limits.
ENV YALENDAR_PUBLIC_AGENT=1
ENV YALENDAR_MAX_COST_TOTAL=0.25
ENV YALENDAR_MAX_QUESTIONS_PER_DAY=60
ENV YALENDAR_MAX_COST_PER_DAY=0.10
ENV YALENDAR_MAX_QUESTIONS_PER_HOUR=5

ENV PORT=8000
ENV YALE_TODAY_DATA=/app/data
ENV YALE_TODAY_HTTPS=1
EXPOSE 8000

# Honour $PORT. Fly is told internal_port = 8000 and would have worked
# either way, but Render, Railway and Koyeb inject their own port and scan
# for a listener on it -- a hardcoded 8000 fails those with "no open ports
# detected", which looks like a broken app rather than a wrong flag.
CMD ["sh", "-c", "exec python -m yale_today serve --host 0.0.0.0 --port ${PORT:-8000}"]
