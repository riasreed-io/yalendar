FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY yale_today ./yale_today
# The agent reads its system prompt from disk at runtime; without this the
# image builds fine and then raises FileNotFoundError on the first question.
COPY prompts ./prompts
# The events snapshot. .dockerignore keeps the session state, the browser
# profile and the dashboard password out of this directory -- check it
# before changing anything here.
COPY data ./data

ENV PORT=8000
ENV YALE_TODAY_DATA=/app/data
ENV YALE_TODAY_HTTPS=1
EXPOSE 8000

CMD ["python", "-m", "yale_today", "serve", "--host", "0.0.0.0", "--port", "8000"]
