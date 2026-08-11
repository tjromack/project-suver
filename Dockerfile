# Suver — container image for a pilot deployment (DEC 035).
# Build:  docker build -t suver .
# Run:    docker run -p 8000:8000 --env-file .env -v suver_data:/app/data suver
#   - .env carries PROVIDER=anthropic + ANTHROPIC_API_KEY (never bake secrets into the image).
#   - the named volume persists data/ (the SQLite accounts DB) across restarts/upgrades.
#   - behind HTTPS, set COOKIE_SECURE=1 and ORG_NAME=<the client's name> in the env.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Install deps first (layer-cached) — copy only requirements, then the app.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/data

EXPOSE 8000
# One worker keeps the in-memory rate limiter + sessions coherent for a pilot; scale out → move those to a shared
# store (see CLIENT-ADAPTATION.md / DESIGN-PARTNER-KIT.md) and raise workers.
# Shell form so we honour the host's $PORT (Render/Fly/Railway inject it); falls back to 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
