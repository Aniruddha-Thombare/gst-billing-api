# Base image
FROM python:3.11-slim

# No .pyc files; log straight to stdout; quieter pip
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first: this layer is rebuilt only when requirements.txt changes
COPY requirements.txt .
RUN pip install -r requirements.txt

# Run as a non-root user: a compromised process cannot modify the image
RUN groupadd --system app && useradd --system --gid app --home-dir /app app

# Application code, Alembic migrations and config
COPY --chown=app:app app ./app
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app alembic.ini .

USER app
EXPOSE 8000

# python is in the image already; slim has no curl
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status==200 else 1)"

# Production-style start (no --reload). docker-compose.yml overrides this for development.
# 2 workers x (pool 20 + overflow 10) = at most 60 DB connections; Postgres allows 100 by default.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
