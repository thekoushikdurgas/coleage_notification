from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import event
from sqlalchemy.engine import Engine
import sqlite3
import queue

db = SQLAlchemy()

# Queues
scrape_queue: queue.Queue = queue.Queue()
scraped_queue: queue.Queue = queue.Queue()
listeners: list[queue.Queue] = []


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA cache_size=-64000")
        cursor.close()


class Organization(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "organizations"

    id = db.Column(db.Integer, primary_key=True)
    aishe_code = db.Column(db.String(50), nullable=True, unique=True, index=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    category = db.Column(
        db.String(50), nullable=False, index=True
    )  # 'college', 'board', 'regulatory_body'
    state = db.Column(db.String(100), nullable=True, index=True)
    district = db.Column(db.String(100), nullable=True, index=True)
    website = db.Column(db.String(255), nullable=True)
    year_of_establishment = db.Column(db.Integer, nullable=True)
    location_type = db.Column(db.String(50), nullable=True)  # 'Rural', 'Urban', etc.
    college_type = db.Column(
        db.String(100), nullable=True
    )  # 'Affiliated College', etc.
    management = db.Column(
        db.String(100), nullable=True
    )  # 'Government', 'Private Un-Aided', etc.
    university_name = db.Column(db.String(255), nullable=True)
    is_tracked = db.Column(db.Boolean, default=True)

    # Relationships
    notifications = db.relationship(
        "Notification", backref="organization", lazy=True, cascade="all, delete-orphan"
    )
    crawler_logs = db.relationship(
        "CrawlerLog", backref="organization", lazy=True, cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "aishe_code": self.aishe_code,
            "name": self.name,
            "category": self.category,
            "state": self.state,
            "district": self.district,
            "website": self.website,
            "year_of_establishment": self.year_of_establishment,
            "location_type": self.location_type,
            "college_type": self.college_type,
            "management": self.management,
            "university_name": self.university_name,
            "is_tracked": self.is_tracked,
        }


class Notification(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True
    )
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    category = db.Column(
        db.String(50), nullable=False, index=True
    )  # 'admission', 'exam', 'result', 'policy', 'scholarship', 'other'

    status = db.Column(
        db.String(50), default="Pending", index=True
    )  # 'Pending', 'Published', 'Duplicate'
    source_url = db.Column(db.String(500), nullable=True)

    # Key extracted dates (as strings/dates)
    application_start_date = db.Column(db.String(100), nullable=True)
    application_end_date = db.Column(db.String(100), nullable=True)
    exam_date = db.Column(db.String(100), nullable=True)
    counselling_date = db.Column(db.String(100), nullable=True)
    merit_list_date = db.Column(db.String(100), nullable=True)

    # Other parsed details
    fee_structure = db.Column(db.String(255), nullable=True)
    scholarship_details = db.Column(db.String(255), nullable=True)
    seat_matrix = db.Column(db.String(255), nullable=True)
    eligibility = db.Column(db.Text, nullable=True)

    # Audit & duplication flags
    is_duplicate = db.Column(db.Boolean, default=False, index=True)
    duplicate_of_id = db.Column(
        db.Integer, db.ForeignKey("notifications.id"), nullable=True
    )
    task_id = db.Column(
        db.Integer, db.ForeignKey("scheduled_tasks.id"), nullable=True, index=True
    )
    run_id = db.Column(
        db.Integer,
        db.ForeignKey("scheduled_task_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    generated_content = db.relationship(
        "GeneratedContent",
        backref="notification",
        uselist=False,
        lazy=True,
        cascade="all, delete-orphan",
    )
    delivery_logs = db.relationship(
        "DeliveryLog", backref="notification", lazy=True, cascade="all, delete-orphan"
    )


class GeneratedContent(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "generated_contents"

    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(
        db.Integer,
        db.ForeignKey("notifications.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    article = db.Column(db.Text, nullable=False)
    meta_title = db.Column(db.String(255), nullable=False)
    meta_description = db.Column(db.Text, nullable=False)
    seo_url = db.Column(db.String(255), nullable=False, unique=True, index=True)
    social_caption = db.Column(db.Text, nullable=True)
    whatsapp_message = db.Column(db.Text, nullable=True)
    telegram_message = db.Column(db.Text, nullable=True)
    push_notification = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Subscription(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    phone = db.Column(db.String(20), nullable=True)

    # Preferences (nullable means match all / wildcards)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id"), nullable=True, index=True
    )
    state = db.Column(db.String(100), nullable=True, index=True)
    category = db.Column(db.String(50), nullable=True)  # e.g., 'admission', 'exam'

    # Enabled channels represented as a comma-separated string e.g., "email,whatsapp"
    channels = db.Column(db.String(100), nullable=False, default="email")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # External Database Push Configuration
    push_db_type = db.Column(db.String(50), nullable=True)  # 'postgres', 'elasticsearch', 'opensearch'
    push_db_config = db.Column(db.Text, nullable=True)      # JSON string containing connection host, credentials, etc.


class CrawlerLog(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "crawler_logs"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True
    )
    task_id = db.Column(
        db.Integer, db.ForeignKey("scheduled_tasks.id"), nullable=True, index=True
    )
    run_id = db.Column(
        db.Integer,
        db.ForeignKey("scheduled_task_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = db.Column(db.String(50), nullable=False)  # 'success', 'failed'
    error_message = db.Column(db.Text, nullable=True)
    detected_changes = db.Column(db.Boolean, default=False)
    crawled_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class DeliveryLog(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "delivery_logs"

    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(
        db.Integer, db.ForeignKey("notifications.id"), nullable=False, index=True
    )
    channel = db.Column(
        db.String(50), nullable=False
    )  # 'email', 'whatsapp', 'telegram', 'push', 'sms'
    recipient = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(50), nullable=False)  # 'success', 'failed'
    sent_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class ScheduledTask(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "scheduled_tasks"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    frequency = db.Column(db.String(50), nullable=False)  # e.g. '30m', '1h', '1d'
    base_frequency = db.Column(
        db.String(50), nullable=True
    )  # Store original frequency when backed off
    target_type = db.Column(db.String(50), nullable=False)  # 'selected', 'state', 'all'
    target_query = db.Column(
        db.Text, nullable=True
    )  # Comma-separated college IDs or State Name
    status = db.Column(db.String(50), default="Active")  # 'Active', 'Paused'
    last_run_at = db.Column(db.DateTime, nullable=True)
    next_run_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    crawler_logs = db.relationship("CrawlerLog", backref="scheduled_task", lazy=True)
    notifications = db.relationship("Notification", backref="scheduled_task", lazy=True)
    runs = db.relationship(
        "ScheduledTaskRun",
        backref="scheduled_task",
        lazy=True,
        cascade="all, delete-orphan",
    )


class ScheduledTaskRun(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "scheduled_task_runs"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(
        db.Integer,
        db.ForeignKey("scheduled_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = db.Column(
        db.String(50), default="Running"
    )  # 'Running', 'Completed', 'Failed'
    trigger_type = db.Column(db.String(50), nullable=False)  # 'Auto', 'Manual'
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    targets_count = db.Column(db.Integer, default=0)
    success_count = db.Column(db.Integer, default=0)
    failed_count = db.Column(db.Integer, default=0)
    notifications_count = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text, nullable=True)


class SystemSetting(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "system_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.String(255), nullable=False)


class CollegeScrapeConfig(db.Model):  # type: ignore[name-defined, misc]
    """
    Stores per-college CSS selector configurations for real web scraping.

    selector_health values:
      - "ok"       : Selectors are working correctly
      - "degraded" : LLM had to recover selectors recently
      - "lost"     : Neither stored selectors nor LLM found notifications
                     Admin must be alerted.

    notification_selectors is a JSON string storing a list of selector configs:
      [
        {
          "css": ".notification-list li",
          "title_attr": "text",
          "link_attr": "a",
          "context": "Main notice board"
        },
        ...
      ]
    """

    __tablename__ = "college_scrape_configs"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # JSON-serialized list of selector dicts
    notification_selectors = db.Column(db.Text, nullable=True)

    # The single selector string that last successfully extracted data
    last_successful_selector = db.Column(db.String(500), nullable=True)

    # Timestamps
    last_scraped_at = db.Column(db.DateTime, nullable=True)
    llm_recovered_at = db.Column(db.DateTime, nullable=True)

    # Health: "ok" | "degraded" | "lost"
    selector_health = db.Column(db.String(20), default="ok", nullable=False)

    # Prevent repeated admin alerts for the same lost selector state
    admin_alerted = db.Column(db.Boolean, default=False)

    # Relationship
    organization = db.relationship(
        "Organization",
        backref=db.backref(
            "scrape_config", uselist=False, cascade="all, delete-orphan"
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "last_successful_selector": self.last_successful_selector,
            "last_scraped_at": (
                self.last_scraped_at.isoformat() if self.last_scraped_at else None
            ),
            "llm_recovered_at": (
                self.llm_recovered_at.isoformat() if self.llm_recovered_at else None
            ),
            "selector_health": self.selector_health,
            "admin_alerted": self.admin_alerted,
        }
