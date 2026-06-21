# FormsADDA – Docker Setup Walkthrough

## What Was Done

The application has been fully containerized and is ready to run on a local Docker host with PostgreSQL.

---

## Files Created / Modified

| File | Status | Purpose |
|---|---|---|
| [Dockerfile](file:///e:/ayan/contact360/docs/codebases/ideas/coleage_notification/Dockerfile) | ✅ Created | Multi-step build: Python 3.11-slim + psycopg2 + Gunicorn |
| [entrypoint.sh](file:///e:/ayan/contact360/docs/codebases/ideas/coleage_notification/entrypoint.sh) | ✅ Created | Waits for Postgres with `pg_isready`, then starts Gunicorn |
| [wsgi.py](file:///e:/ayan/contact360/docs/codebases/ideas/coleage_notification/wsgi.py) | ✅ Created | Gunicorn entry point – calls `initialize_system()` on cold boot |
| [docker-compose.yml](file:///e:/ayan/contact360/docs/codebases/ideas/coleage_notification/docker-compose.yml) | ✅ Created | Orchestrates `web` (Gunicorn) + `db` (PostgreSQL 16) services |
| [.env.example](file:///e:/ayan/contact360/docs/codebases/ideas/coleage_notification/.env.example) | ✅ Created | Template for all required environment variables |
| [.dockerignore](file:///e:/ayan/contact360/docs/codebases/ideas/coleage_notification/.dockerignore) | ✅ Created | Excludes venv, SQLite files, secrets from build context |
| [nginx/formsadda.conf](file:///e:/ayan/contact360/docs/codebases/ideas/coleage_notification/nginx/formsadda.conf) | ✅ Created | Nginx reverse proxy; SSE buffering disabled on `/stream` |
| [requirements.txt](file:///e:/ayan/contact360/docs/codebases/ideas/coleage_notification/requirements.txt) | ✅ Updated | Added `gunicorn==22.0.0` and `psycopg2-binary==2.9.9` |
| [app/config.py](file:///e:/ayan/contact360/docs/codebases/ideas/coleage_notification/app/config.py) | ✅ Updated | `DATABASE_URL` env var overrides SQLite fallback |

---

## Architecture

```
Browser / Client
      │
      ▼
 [Nginx :80]          ← host machine (external reverse proxy)
      │  proxy_pass
      ▼
 [Gunicorn :8000]     ← web container (formsadda_web)
      │  SQLAlchemy
      ▼
 [PostgreSQL :5432]   ← db container  (formsadda_db)
      │  volume
      ▼
 postgres_data        ← named Docker volume (persisted)
```

> [!IMPORTANT]
> SSE (`/stream`) requires `proxy_buffering off` in Nginx – this is already set in `nginx/formsadda.conf`.

---

## How to Run Locally

### 1 – Copy and configure the env file
```bash
cp .env.example .env
# Edit .env: set SECRET_KEY, POSTGRES_PASSWORD, GEMINI_API_KEY (optional)
```

### 2 – Build and start
```bash
docker compose up --build
```

On first boot the `web` container will:
1. Wait for PostgreSQL to be ready (`pg_isready`).
2. Call `db.create_all()` to create all tables.
3. Seed organizations from the Excel file in `inputs/` (takes ~10–15 s).
4. Start Gunicorn on port `8000`.

### 3 – Access the app
| Endpoint | URL |
|---|---|
| Public feed | http://localhost:8000 |
| Student inbox | http://localhost:8000/student-inbox |
| Admin dashboard | http://localhost:8000/admin |

### 4 – Useful commands
```bash
# View live logs
docker compose logs -f

# Stop containers (data preserved)
docker compose down

# Wipe the database volume completely
docker compose down -v

# Rebuild only the web image
docker compose build web && docker compose up web
```

---

## Nginx Setup (on host)

```bash
sudo cp nginx/formsadda.conf /etc/nginx/sites-available/formsadda.conf
sudo ln -s /etc/nginx/sites-available/formsadda.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

For **HTTPS** add Let's Encrypt via Certbot:
```bash
sudo certbot --nginx -d yourdomain.com
```

---

## Key Design Decisions

- **Single Gunicorn worker** (`--workers 1`) – safe for the SSE broadcast system which uses in-process queues. Increase only if you switch to Redis Pub/Sub for SSE.
- **PostgreSQL 16-alpine** – lightweight, production-grade, persisted via named volume.
- **`inputs/` mounted read-only** – the large Excel seed files (~45 MB) are mounted from host into the container so the Docker build context stays small.
- **`pg_isready` healthcheck** – the `web` container won't start until `db` is accepting connections, preventing race-condition errors on cold boot.
Listed directory coleage_notification
Viewed docker-compose.yml:1-52
Viewed wsgi.py:1-42
Viewed entrypoint.sh:1-48
Viewed seed.py:1-226
Viewed error.txt:1-31
Viewed __init__.py:1-66
Viewed run.py:1-41
Viewed Dockerfile:1-38
Edited docker-compose.yml
Edited wsgi.py
Edited wsgi.py

I have updated the codebase configuration so that database seeding is completely separated from the server startup process.

Here is a summary of the changes made:
1. **Added a dedicated `seeder` service in [docker-compose.yml](file:///e:/ayan/contact360/docs/codebases/ideas/coleage_notification/docker-compose.yml):** 
   - Defined under the `seed` compose profile. It runs `python seed.py` and correctly awaits the PostgreSQL database container health check before starting.
2. **Updated [wsgi.py](file:///e:/ayan/contact360/docs/codebases/ideas/coleage_notification/wsgi.py):**
   - Removed the automatic check & seeding logic from `wsgi.py`.
   - Now, it only ensures the database tables/schema exist (`db.create_all()`) on startup, allowing the web server to start instantly without blocking.

### How to Deploy

To deploy, run the following steps in sequence:

1. **Start the database service first:**
   ```bash
   docker compose up db -d
   ```

2. **Run the one-time seeder service (uses the `seed` profile):**
   ```bash
   docker compose run --rm seeder
   ```
   *(This will parse the Excel files in `inputs/` and seed them to PostgreSQL. It runs to completion and exits, cleanup happens automatically due to `--rm`.)*

3. **Deploy the application server:**
   ```bash
   docker compose up web -d
   ```
   *(Since seeding is already completed, Gunicorn will spin up immediately without any delay!)*

   