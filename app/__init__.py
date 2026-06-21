from flask import Flask
from app.config import Config
from app.database import db

# Module-level flag: workers are started at most once per process.
# This prevents double-spawning when create_app() is called multiple times
# (e.g. from wsgi.py and indirectly from seed.py in the same process).
_workers_started = False


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialize database
    db.init_app(app)
    
    # Ensure database schema has base_frequency column
    with app.app_context():
        try:
            db.create_all()
            db.session.execute(db.text("ALTER TABLE scheduled_tasks ADD COLUMN base_frequency VARCHAR(50)"))
            db.session.commit()
        except Exception:
            pass
    
    # Register routes blueprint
    from app.routes import main_bp
    app.register_blueprint(main_bp)
    
    # Custom Jinja2 filters for clean template display
    @app.template_filter('format_date')
    def format_date_filter(value):
        if not value:
            return 'N/A'
        return value
        
    @app.template_filter('badge_class')
    def badge_class_filter(category):
        classes = {
            'admission': 'badge-admission',
            'exam': 'badge-exam',
            'result': 'badge-result',
            'policy': 'badge-policy',
            'scholarship': 'badge-scholarship',
            'other': 'badge-other'
        }
        return classes.get(category.lower(), 'badge-other')

    # Global context processor to inject recent logs into all template headers
    @app.context_processor
    def inject_global_data():
        from app.database import CrawlerLog
        from sqlalchemy.orm import joinedload
        try:
            recent_logs = CrawlerLog.query.options(
                joinedload(CrawlerLog.organization)
            ).order_by(CrawlerLog.crawled_at.desc()).limit(5).all()
        except Exception:
            recent_logs = []
        return dict(global_recent_logs=recent_logs, min=min, max=max)


    # Start background worker threads exactly once per process.
    # Under Werkzeug dev server, only start after the reloader has forked
    # (WERKZEUG_RUN_MAIN == 'true').  Under Gunicorn (not app.debug), start
    # immediately, but the module-level flag ensures we only do it once.
    global _workers_started
    import os
    should_start = (
        os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug
    )
    if should_start and not _workers_started:
        from app.workers import start_workers
        start_workers(app)
        _workers_started = True

    return app
