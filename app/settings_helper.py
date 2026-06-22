"""
settings_helper.py — Centralized settings accessor for FormsADDA.

All application settings are stored in the SystemSetting DB table (key-value).
On first access, if a key doesn't exist in the DB, the default from SETTING_DEFAULTS
is used.  .env values serve as initial overrides at app startup.
"""

import os
from app.database import db, SystemSetting


# ── Canonical setting keys and their defaults ──────────────────────────────────
SETTING_DEFAULTS = {
    # AI Provider: 'gemini', 'ollama', or 'none'
    "ai_provider": os.environ.get("AI_PROVIDER", "gemini"),

    # Gemini (Online AI)
    "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
    "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),

    # Ollama (Local AI)
    "ollama_host": os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
    "ollama_model": os.environ.get("OLLAMA_MODEL", "gemma2"),

    # Notification workflow
    "auto_approve_notifications": "false",
    "content_generation_enabled": "true",
    "alert_dispatch_enabled": "true",

    # Scraper tuning
    "scraper_timeout": os.environ.get("SCRAPER_TIMEOUT", "12"),
    "scraper_user_agent": os.environ.get(
        "SCRAPER_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36",
    ),
    "llm_html_char_limit": os.environ.get("LLM_HTML_CHAR_LIMIT", "18000"),
}


def get_setting(key: str, default=None) -> str:
    """
    Read a single setting from the database.
    Falls back to SETTING_DEFAULTS if the key has never been persisted.
    """
    row = SystemSetting.query.filter_by(key=key).first()
    if row:
        return row.value
    # Not in DB yet — return the canonical default (or caller-supplied fallback)
    return SETTING_DEFAULTS.get(key, default or "")


def set_setting(key: str, value: str) -> None:
    """
    Create or update a setting in the database.
    """
    row = SystemSetting.query.filter_by(key=key).first()
    if row:
        row.value = value
    else:
        db.session.add(SystemSetting(key=key, value=value))
    db.session.commit()


def get_all_settings() -> dict:
    """
    Return a merged dict: defaults overridden by anything stored in DB.
    """
    merged = dict(SETTING_DEFAULTS)
    rows = SystemSetting.query.all()
    for row in rows:
        merged[row.key] = row.value
    return merged


def reset_all_settings() -> None:
    """
    Delete all DB-persisted settings so the app reverts to SETTING_DEFAULTS.
    """
    SystemSetting.query.delete()
    db.session.commit()
