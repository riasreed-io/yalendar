FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY yale_today ./yale_today
COPY data ./data

ENV PORT=8000
ENV YALE_TODAY_DATA=/app/data
ENV YALE_TODAY_HTTPS=1
EXPOSE 8000

CMD ["python", "-m", "yale_today", "serve", "--host", "0.0.0.0", "--port", "8000"]
