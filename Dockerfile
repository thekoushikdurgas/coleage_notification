# ─────────────────────────────────────────────────────────────────────────────
# FormsADDA – Production Dockerfile
#
#  Build:   docker build -t formsadda:latest .
#  Run:     see docker-compose.yml
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# System packages:
#   gcc + libpq-dev  → build psycopg2-binary
#   postgresql-client → gives us pg_isready for healthchecks in entrypoint.sh
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc \
       libpq-dev \
       postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Layer-cache: install Python deps before copying app code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Gunicorn listens on this port (proxied by Nginx on the host)
EXPOSE 8000

# Keep stdout/stderr unbuffered so logs appear immediately in docker logs
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["./entrypoint.sh"]
