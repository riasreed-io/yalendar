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
ENV PORT=8000
ENV YALE_TODAY_DATA=/app/data
ENV YALE_TODAY_HTTPS=1
EXPOSE 8000

CMD ["python", "-m", "yale_today", "serve", "--host", "0.0.0.0", "--port", "8000"]
