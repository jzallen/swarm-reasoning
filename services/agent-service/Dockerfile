FROM python:3.11-slim AS production
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

USER nobody
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=10s --retries=5 --start-period=30s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["python", "-m", "swarm_reasoning.worker"]
