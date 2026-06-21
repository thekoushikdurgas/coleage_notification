"""
wsgi.py – Gunicorn entry point for FormsADDA.

Gunicorn command:
    gunicorn wsgi:app -b 0.0.0.0:8000 --workers 1

This module creates the Flask application exactly ONCE.
initialize_system() receives the already-created app so seed.py
never calls create_app() a second time.
"""
from app import create_app
from app.database import db


# ── Create the app exactly once ───────────────────────────────────────────────
app = create_app()


def create_schema_if_needed():
    """
    Creates DB tables/schema if they do not exist.
    Does NOT seed data. Seeding is run as a separate one-time step.
    """
    with app.app_context():
        db.create_all()


# Initialize database schema on startup
create_schema_if_needed()

