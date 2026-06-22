from flask import Blueprint, Response
from flask import render_template, request, redirect, url_for, flash, jsonify
from app.database import (
    db,
    Organization,
    Notification,
    GeneratedContent,
    Subscription,
    CrawlerLog,
    DeliveryLog,
    ScheduledTask,
    ScheduledTaskRun,
    SystemSetting,
)
from app.ai_engine import AIEngine
from app.settings_helper import get_setting, set_setting, get_all_settings, reset_all_settings, SETTING_DEFAULTS
from datetime import datetime, timedelta
import random
import re
import json
import queue

main_bp = Blueprint("main", __name__)


# --- Helper: Alert Dispatcher Matching Engine ---
def dispatch_alerts(notification_id):
    """
    Finds all subscriptions matching a newly published notification
    and logs simulated delivery tasks (Email, WhatsApp, Telegram, Push, SMS).
    """
    notif = Notification.query.get(notification_id)
    if not notif or notif.is_duplicate:
        return 0

    org = notif.organization
    content = notif.generated_content
    if not content:
        # Ensure content is generated if not done already
        content = AIEngine.generate_content(notification_id)

    # Find matching subscriptions
    # Match criteria:
    # 1. Organization matches OR organization is null (match all)
    # 2. State matches OR state is null (match all)
    # 3. Category matches OR category is null (match all)

    query = Subscription.query

    # We fetch all subscriptions and filter in Python to support complex fallback logic
    all_subs = query.all()
    matching_subs = []

    for sub in all_subs:
        match_org = (
            sub.organization_id is None or sub.organization_id == notif.organization_id
        )
        match_state = sub.state is None or sub.state == org.state
        match_cat = sub.category is None or sub.category == notif.category

        if match_org and match_state and match_cat:
            matching_subs.append(sub)

    alerts_sent = 0
    import json
    from app.db_pusher import push_to_external_db

    for sub in matching_subs:
        # Parse channels
        channels = [ch.strip() for ch in sub.channels.split(",") if ch.strip()]
        for channel in channels:
            status = "success"
            recipient = ""
            
            if channel == "db_push":
                db_config = {}
                if sub.push_db_config:
                    try:
                        db_config = json.loads(sub.push_db_config)
                    except Exception:
                        pass
                
                db_type = sub.push_db_type or "postgres"
                host = db_config.get("host", "localhost")
                port = db_config.get("port", "")
                database = db_config.get("database", "")
                recipient = f"{db_type.upper()}://{host}:{port}/{database}"
                
                try:
                    payload = {
                        "notification_id": notif.id,
                        "title": notif.title,
                        "category": notif.category,
                        "body": notif.body,
                        "organization_name": org.name,
                        "state": org.state,
                        "seo_url": content.seo_url if content else "",
                        "meta_description": content.meta_description if content else "",
                        "pushed_at": datetime.utcnow().isoformat()
                    }
                    push_to_external_db(db_type, db_config, payload)
                except Exception as e:
                    status = "failed"
                    print(f"Failed to push alert to external DB: {e}")
            else:
                recipient = (
                    sub.email
                    if channel == "email" or channel == "push"
                    else (sub.phone or "Simulated Phone")
                )

            log = DeliveryLog(
                notification_id=notif.id,
                channel=channel,
                recipient=recipient,
                status=status,
                sent_at=datetime.utcnow(),
            )
            db.session.add(log)
            alerts_sent += 1

    db.session.commit()

    # Broadcast alerts to SSE listeners
    try:
        from app.workers import broadcast_sse

        for sub in matching_subs:
            channels = [ch.strip() for ch in sub.channels.split(",") if ch.strip()]
            for channel in channels:
                if channel == "db_push":
                    db_config = {}
                    if sub.push_db_config:
                        try:
                            db_config = json.loads(sub.push_db_config)
                        except Exception:
                            pass
                    db_type = sub.push_db_type or "postgres"
                    recipient = f"{db_type.upper()}://{db_config.get('host', 'localhost')}:{db_config.get('port', '')}/{db_config.get('database', '')}"
                    msg_text = f"Pushed notification payload successfully to {db_type.upper()} table/index."
                else:
                    recipient = (
                        sub.email
                        if channel == "email" or channel == "push"
                        else (sub.phone or "Simulated Phone")
                    )
                    msg_text = (
                        content.meta_description if content else "Announcement posted!"
                    )
                    if content:
                        if channel == "whatsapp":
                            msg_text = content.whatsapp_message
                        elif channel == "telegram":
                            msg_text = content.telegram_message
                        elif channel == "push":
                            msg_text = content.push_notification

                broadcast_sse(
                    "delivery_log",
                    {
                        "channel": channel,
                        "recipient": recipient,
                        "title": notif.title,
                        "text": msg_text,
                        "time": datetime.now().strftime("%I:%M %p | %d %b %Y"),
                        "org_name": org.name,
                    },
                )

        # Broadcast published notification to SSE
        broadcast_sse(
            "published_notification",
            {
                "id": notif.id,
                "title": notif.title,
                "category": notif.category,
                "organization_name": org.name,
                "state": org.state or "N/A",
                "seo_url": content.seo_url if content else "",
                "created_at": notif.created_at.strftime("%I:%M %p | %d %b %Y"),
                "body_preview": (
                    (notif.body[:150] + "...") if len(notif.body) > 150 else notif.body
                ),
            },
        )
    except Exception as e:
        print(f"Error broadcasting delivery or published log: {e}")

    return alerts_sent


# --- Public Routes ---


@main_bp.route("/")
def index():
    """
    Public feed page. Displays active, published notifications.
    Supports filtering by state, category, organization, and search query.
    """
    from sqlalchemy.orm import joinedload

    query = (
        Notification.query.join(Organization)
        .options(
            joinedload(Notification.organization),
            joinedload(Notification.generated_content),
        )
        .filter(~Notification.is_duplicate, Notification.status == "Published")
    )

    # Apply filters
    state_filter = request.args.get("state")
    cat_filter = request.args.get("category")
    org_filter = request.args.get("org_id")
    search_query = request.args.get("q")
    page = request.args.get("page", 1, type=int)

    if state_filter:
        query = query.filter(Organization.state == state_filter)
    if cat_filter:
        query = query.filter(Notification.category == cat_filter)
    if org_filter:
        query = query.filter(Notification.organization_id == org_filter)
    if search_query:
        query = query.filter(
            (Notification.title.like(f"%{search_query}%"))
            | (Organization.name.like(f"%{search_query}%"))
        )

    # Paginate: 20 per page for fast loads
    per_page = 20
    pagination = query.order_by(Notification.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    notifications = pagination.items

    # Fetch states and categories for filter dropdowns
    states = (
        db.session.query(Organization.state)
        .filter(Organization.state.isnot(None))
        .distinct()
        .order_by(Organization.state)
        .all()
    )
    states = [s[0] for s in states]

    categories = ["admission", "exam", "result", "policy", "scholarship", "other"]

    # Retrieve top 5 trending (most notifications count)
    trending = (
        db.session.query(
            Organization, db.func.count(Notification.id).label("notif_count")
        )
        .join(Notification)
        .filter(Notification.status == "Published")
        .group_by(Organization)
        .order_by(db.desc("notif_count"))
        .limit(5)
        .all()
    )

    return render_template(
        "index.html",
        notifications=notifications,
        pagination=pagination,
        states=states,
        categories=categories,
        trending=trending,
        selected_state=state_filter,
        selected_cat=cat_filter,
        search_query=search_query,
    )


@main_bp.route("/notifications/<seo_url>")
def notification_detail(seo_url):
    """
    Programmatic SEO landing page. Displays the full AI-generated article and meta tags.
    """
    content = GeneratedContent.query.filter_by(seo_url=seo_url).first_or_404()
    notif = content.notification
    org = notif.organization

    # Also fetch related notifications (same state or same category)
    related = (
        Notification.query.join(Organization)
        .filter(
            Notification.id != notif.id,
            Notification.status == "Published",
            ~Notification.is_duplicate,
            (Notification.category == notif.category)
            | (Organization.state == org.state),
        )
        .limit(3)
        .all()
    )

    return render_template(
        "notification.html",
        content=content,
        notification=notif,
        organization=org,
        related=related,
    )


@main_bp.route("/subscribe", methods=["GET", "POST"])
def subscribe():
    """
    Student subscription registration page.
    """
    if request.method == "POST":
        email = request.form.get("email")
        phone = request.form.get("phone")
        state = request.form.get("state")
        category = request.form.get("category")
        org_id = request.form.get("org_id")
        channels_list = request.form.getlist("channels")

        if not email:
            flash("Email address is required!", "error")
            return redirect(url_for("main.subscribe"))

        if not channels_list:
            channels_list = ["email"]

        # Parse organization ID
        parsed_org_id = None
        if org_id and org_id.isdigit():
            parsed_org_id = int(org_id)

        # Save subscription
        push_db_type = None
        push_db_config = None
        if "db_push" in channels_list:
            push_db_type = request.form.get("push_db_type")
            db_config_dict = {
                "host": request.form.get("push_db_host"),
                "port": request.form.get("push_db_port"),
                "database": request.form.get("push_db_name"),
                "user": request.form.get("push_db_user"),
                "password": request.form.get("push_db_password"),
                "table_or_index": request.form.get("push_db_table_or_index"),
                "ssl_mode": request.form.get("push_db_ssl_mode") or "disable"
            }
            push_db_config = json.dumps(db_config_dict)

        sub = Subscription(
            email=email,
            phone=phone,
            organization_id=parsed_org_id,
            state=state if state else None,
            category=category if category else None,
            channels=",".join(channels_list),
            push_db_type=push_db_type,
            push_db_config=push_db_config,
        )

        db.session.add(sub)
        db.session.commit()

        flash(
            "Successfully subscribed! You will receive alerts when matching announcements are published.",
            "success",
        )
        return redirect(url_for("main.index"))

    # GET Request: Renders the subscription form
    states = (
        db.session.query(Organization.state)
        .filter(Organization.state.isnot(None))
        .distinct()
        .order_by(Organization.state)
        .all()
    )
    states = [s[0] for s in states]

    categories = ["admission", "exam", "result", "policy", "scholarship", "other"]

    # Get a list of active top tracked organizations for easy selection
    colleges = (
        Organization.query.filter_by(category="college")
        .order_by(Organization.name)
        .limit(100)
        .all()
    )
    boards = Organization.query.filter_by(category="board").all()
    regulators = Organization.query.filter_by(category="regulatory_body").all()

    return render_template(
        "subscribe.html",
        states=states,
        categories=categories,
        colleges=colleges,
        boards=boards,
        regulators=regulators,
    )


@main_bp.route("/test-db-connection", methods=["POST"])
def test_db_connection():
    """
    AJAX API to test connection to an external database (PostgreSQL, Elasticsearch, OpenSearch).
    """
    from flask import jsonify
    from app.db_pusher import verify_external_db_connection

    db_type = request.form.get("db_type")
    host = request.form.get("host")
    port = request.form.get("port")
    database = request.form.get("database")
    user = request.form.get("user")
    password = request.form.get("password")
    table_or_index = request.form.get("table_or_index")
    ssl_mode = request.form.get("ssl_mode") or "disable"

    if not db_type or not host or not port or not database:
        return jsonify({
            "success": False,
            "message": "Database Type, Host, Port, and Database/Index name are required fields."
        })

    config = {
        "host": host,
        "port": port,
        "database": database,
        "user": user,
        "password": password,
        "table_or_index": table_or_index,
        "ssl_mode": ssl_mode
    }

    success, message = verify_external_db_connection(db_type, config)
    return jsonify({"success": success, "message": message})


@main_bp.route("/student-inbox")
def student_inbox():
    """
    Renders the visual Student Inbox simulator.
    Shows the generated alerts dispatched to students (Email, WhatsApp, Telegram, etc.).
    """
    from sqlalchemy.orm import joinedload

    delivery_logs = (
        DeliveryLog.query.options(
            joinedload(DeliveryLog.notification).joinedload(Notification.organization),
            joinedload(DeliveryLog.notification).joinedload(
                Notification.generated_content
            ),
        )
        .order_by(DeliveryLog.sent_at.desc())
        .limit(100)
        .all()
    )

    # We enrich logs with notification titles and message contents
    messages = []
    for log in delivery_logs:
        notif = log.notification
        content = notif.generated_content if notif else None

        msg_text = "Announcement posted!"
        if content:
            if log.channel == "whatsapp":
                msg_text = content.whatsapp_message
            elif log.channel == "telegram":
                msg_text = content.telegram_message
            elif log.channel == "push":
                msg_text = content.push_notification
            else:
                msg_text = content.meta_description  # Fallback for email / sms

        messages.append(
            {
                "id": log.id,
                "channel": log.channel,
                "recipient": log.recipient,
                "title": notif.title if notif else "Notification Update",
                "text": msg_text,
                "time": log.sent_at.strftime("%I:%M %p | %d %b %Y"),
                "org_name": notif.organization.name if notif else "FormsADDA",
            }
        )

    return render_template("student_inbox.html", messages=messages)


@main_bp.before_app_request
def check_role():
    from flask import session

    if "user_role" not in session:
        session["user_role"] = "admin"

    if request.path.startswith("/admin"):
        if request.path in ["/admin/stream-events", "/admin/api/pending-notifications"]:
            return

        role = session.get("user_role")
        if role == "student":
            flash(
                "Access denied: Students are not authorized to access administrative panels.",
                "danger",
            )
            return redirect(url_for("main.index"))

        if role == "moderator":
            # Moderators cannot run crawls, create/edit/delete/toggle tasks or colleges
            restricted_keywords = [
                "/crawl",
                "/bulk-crawl",
                "/create",
                "/edit",
                "/delete",
                "/toggle",
                "/run/",
            ]
            if any(kw in request.path for kw in restricted_keywords):
                flash(
                    "Access denied: Moderators cannot perform configuration or manual trigger actions.",
                    "warning",
                )
                return redirect(url_for("main.admin_dashboard"))


@main_bp.route("/set-role/<role>")
def set_role(role):
    if role in ["admin", "moderator", "student"]:
        from flask import session

        session["user_role"] = role
        flash(f"User role switched to {role.capitalize()}.", "success")
    return redirect(request.referrer or url_for("main.index"))


@main_bp.route("/stream-events")
@main_bp.route("/admin/stream-events")
def admin_stream_events():
    """
    Server-Sent Events endpoint to stream real-time worker logs, statuses, and notices.
    """
    from app.workers import (
        sse_listeners,
        listeners_lock,
        scraper_status,
        loader_status,
        scrape_queue,
        scraped_queue,
    )

    def event_stream():
        q = queue.Queue(maxsize=100)
        with listeners_lock:
            sse_listeners.append(q)

        # Immediately send initial status to the connecting client
        initial_status = {
            "scraper": scraper_status,
            "loader": loader_status,
            "scrape_queue_size": scrape_queue.qsize(),
            "scraped_queue_size": scraped_queue.qsize(),
            "total_backlog": scrape_queue.qsize() + scraped_queue.qsize(),
        }
        yield f"event: status\ndata: {json.dumps(initial_status)}\n\n"

        try:
            while True:
                try:
                    # Dequeue with timeout of 15 seconds to yield a ping
                    event = q.get(timeout=15.0)
                    yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
                    q.task_done()
                except queue.Empty:
                    # Connection keep-alive ping
                    yield f"event: ping\ndata: {json.dumps({'time': datetime.now().strftime('%H:%M:%S')})}\n\n"
        except GeneratorExit:
            # Handle client disconnect cleanly
            pass
        finally:
            with listeners_lock:
                if q in sse_listeners:
                    sse_listeners.remove(q)

    return Response(event_stream(), mimetype="text/event-stream")


# --- Admin Dashboard & Simulation Routes ---


@main_bp.route("/admin")
def admin_dashboard():
    """
    Admin dashboard. Displays statistics, moderation queue, sources registry, and simulator.
    """
    # Counters (optimized with grouped/single queries)
    counts = (
        db.session.query(Organization.category, db.func.count(Organization.id))
        .group_by(Organization.category)
        .all()
    )
    counts_map = dict(counts)
    total_colleges = counts_map.get("college", 0)
    total_boards = counts_map.get("board", 0)
    total_regulators = counts_map.get("regulatory_body", 0)

    stats = db.session.query(
        db.func.count(Notification.id),
        db.func.sum(db.case((Notification.status == "Published", 1), else_=0)),
        db.func.sum(db.case((Notification.status == "Pending", 1), else_=0)),
        db.func.sum(db.case((Notification.is_duplicate, 1), else_=0)),
    ).first()

    total_notifs = stats[0] or 0
    total_published = stats[1] or 0
    total_pending = stats[2] or 0
    total_duplicates = stats[3] or 0

    total_alerts = DeliveryLog.query.count()
    total_subs = Subscription.query.count()

    # Moderation Queue (Notifications in 'Pending' status)
    from sqlalchemy.orm import joinedload

    moderation_queue = (
        Notification.query.options(
            joinedload(Notification.organization),
            joinedload(Notification.generated_content),
        )
        .filter_by(status="Pending")
        .order_by(Notification.created_at.desc())
        .all()
    )

    # Recent Crawl Logs
    recent_crawls = (
        CrawlerLog.query.options(joinedload(CrawlerLog.organization))
        .order_by(CrawlerLog.crawled_at.desc())
        .limit(15)
        .all()
    )

    # Sample list of organizations for manual crawl trigger
    orgs_query = Organization.query

    search_q = request.args.get("org_q")
    if search_q:
        orgs_query = orgs_query.filter(Organization.name.like(f"%{search_q}%"))

    organizations = (
        orgs_query.order_by(Organization.category, Organization.name).limit(50).all()
    )

    # Query auto-approve setting
    setting = SystemSetting.query.filter_by(key="auto_approve_notifications").first()
    auto_approve_enabled = (setting.value == "true") if setting else False

    return render_template(
        "admin.html",
        total_colleges=total_colleges,
        total_boards=total_boards,
        total_regulators=total_regulators,
        total_notifs=total_notifs,
        total_published=total_published,
        total_pending=total_pending,
        total_duplicates=total_duplicates,
        total_alerts=total_alerts,
        total_subs=total_subs,
        moderation_queue=moderation_queue,
        recent_crawls=recent_crawls,
        organizations=organizations,
        org_search=search_q,
        auto_approve_enabled=auto_approve_enabled,
    )


@main_bp.route("/admin/crawl/<int:org_id>", methods=["POST"])
def manual_crawl(org_id):
    """
    Manually triggers a simulated crawl for a specific organization in the background.
    """
    org = Organization.query.get_or_404(org_id)
    from app.workers import scrape_queue, log_to_workers, broadcast_status

    scrape_queue.put((org.id, None))
    log_to_workers(
        f"Manual crawl request received for '{org.name}' and queued.", "info"
    )
    broadcast_status()

    return jsonify(
        {
            "success": True,
            "message": f"Simulated crawl request for '{org.name}' queued in background.",
        }
    )


@main_bp.route("/admin/bulk-crawl", methods=["POST"])
def bulk_crawl():
    """
    Trigger simulated crawling cycles for a random batch of 5 organizations in the background.
    """
    all_orgs = Organization.query.filter_by(is_tracked=True).all()
    if not all_orgs:
        return jsonify(
            {"success": False, "message": "No registered organizations found."}
        )

    selected_orgs = random.sample(all_orgs, min(5, len(all_orgs)))
    from app.workers import scrape_queue, log_to_workers, broadcast_status

    for org in selected_orgs:
        scrape_queue.put((org.id, None))

    log_to_workers(
        "Bulk crawl request received. Queued 5 organizations in background.", "info"
    )
    broadcast_status()

    return jsonify(
        {
            "success": True,
            "message": f"Bulk crawl request for {len(selected_orgs)} organizations queued in background.",
        }
    )


@main_bp.route("/admin/approve/<int:notif_id>", methods=["POST"])
def approve_notification(notif_id):
    """
    Moderation action: Approves a pending notification, changing status to 'Published'
    and fanning out notifications to all matched student subscribers.
    """
    notif = Notification.query.get_or_404(notif_id)
    notif.status = "Published"
    db.session.commit()

    # Dispatch student alerts
    alerts_sent = dispatch_alerts(notif.id)

    flash(
        f"Notification '{notif.title}' approved and published. {alerts_sent} alerts dispatched to subscribers.",
        "success",
    )
    return redirect(url_for("main.admin_dashboard"))


@main_bp.route("/admin/reject/<int:notif_id>", methods=["POST"])
def reject_notification(notif_id):
    """
    Moderation action: Rejects and removes a pending notification from the queue.
    """
    notif = Notification.query.get_or_404(notif_id)
    title = notif.title
    db.session.delete(notif)
    db.session.commit()

    flash(f"Notification '{title}' removed from queue.", "info")
    return redirect(url_for("main.admin_dashboard"))


@main_bp.route("/admin/approve-all", methods=["POST"])
def approve_all_notifications():
    """
    Moderation action: Approves all pending notifications, changing their status to 'Published'
    and fanning out notifications to all matched student subscribers.
    """
    pending_notifs = Notification.query.filter_by(status="Pending").all()
    if not pending_notifs:
        flash("No pending notifications to approve.", "info")
        return redirect(url_for("main.admin_dashboard"))

    total_approved = len(pending_notifs)
    notif_ids = [n.id for n in pending_notifs]

    # Step 1: Set all to Published and commit so dispatch_alerts can see the change
    for notif in pending_notifs:
        notif.status = "Published"
    db.session.commit()

    # Step 2: Dispatch alerts for each newly published notification
    total_alerts_sent = 0
    for notif_id in notif_ids:
        alerts_sent = dispatch_alerts(notif_id)
        total_alerts_sent += alerts_sent

    flash(
        f"Successfully approved all {total_approved} pending notifications. {total_alerts_sent} alerts dispatched to subscribers.",
        "success",
    )
    return redirect(url_for("main.admin_dashboard"))


@main_bp.route("/admin/settings/toggle-auto-approve", methods=["POST"])
def toggle_auto_approve():
    """
    Toggles the global auto-approve setting.
    """
    setting = SystemSetting.query.filter_by(key="auto_approve_notifications").first()
    if not setting:
        setting = SystemSetting(key="auto_approve_notifications", value="false")
        db.session.add(setting)

    # Toggle logic
    if setting.value == "true":
        setting.value = "false"
    else:
        setting.value = "true"

    db.session.commit()
    state_str = "enabled" if setting.value == "true" else "disabled"
    flash(f"Global Auto-Approve of notifications is now {state_str}.", "success")
    return redirect(url_for("main.admin_dashboard"))


# --- AJAX Moderation API Routes (used by the admin review panel) ---


@main_bp.route("/admin/api/approve/<int:notif_id>", methods=["POST"])
def ajax_approve_notification(notif_id):
    """
    AJAX: Approve a single pending notification and dispatch alerts.
    Returns JSON so the admin panel can update the UI without page reload.
    """
    notif = Notification.query.get_or_404(notif_id)
    if notif.status != "Pending":
        return jsonify(
            {"success": False, "message": "Notification is not in Pending state."}
        )

    notif.status = "Published"
    db.session.commit()
    alerts_sent = dispatch_alerts(notif.id)

    return jsonify(
        {
            "success": True,
            "notif_id": notif_id,
            "alerts_sent": alerts_sent,
            "message": f"Approved & published. {alerts_sent} alerts dispatched.",
        }
    )


@main_bp.route("/admin/api/reject/<int:notif_id>", methods=["POST"])
def ajax_reject_notification(notif_id):
    """
    AJAX: Reject and delete a pending notification.
    Returns JSON for seamless inline UI update.
    """
    notif = Notification.query.get_or_404(notif_id)
    title = notif.title[:60]
    db.session.delete(notif)
    db.session.commit()

    return jsonify(
        {
            "success": True,
            "notif_id": notif_id,
            "message": f"Notification discarded: '{title}'",
        }
    )


@main_bp.route("/admin/api/pending-notifications")
def api_pending_notifications():
    """
    AJAX: Returns paginated pending notifications as JSON for the admin review panel.
    Supports page, per_page, search_q query params.
    """
    from sqlalchemy.orm import joinedload

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    search_q = request.args.get("q", "").strip()

    query = (
        Notification.query.join(Organization)
        .options(
            joinedload(Notification.organization),
            joinedload(Notification.generated_content),
        )
        .filter(Notification.status == "Pending")
    )

    if search_q:
        query = query.filter(
            (Notification.title.like(f"%{search_q}%"))
            | (Organization.name.like(f"%{search_q}%"))
        )

    pagination = query.order_by(Notification.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for n in pagination.items:
        items.append(
            {
                "id": n.id,
                "title": n.title,
                "body_preview": (
                    (n.body[:200] + "...")
                    if n.body and len(n.body) > 200
                    else (n.body or "")
                ),
                "category": n.category,
                "organization_name": (
                    n.organization.name if n.organization else "Unknown"
                ),
                "organization_state": n.organization.state if n.organization else "",
                "organization_category": (
                    n.organization.category if n.organization else ""
                ),
                "source_url": n.source_url or "",
                "application_start_date": n.application_start_date or "",
                "application_end_date": n.application_end_date or "",
                "exam_date": n.exam_date or "",
                "created_at": (
                    n.created_at.strftime("%d %b %Y, %I:%M %p") if n.created_at else ""
                ),
                "has_content": n.generated_content is not None,
                "seo_url": n.generated_content.seo_url if n.generated_content else "",
            }
        )

    return jsonify(
        {
            "success": True,
            "items": items,
            "total": pagination.total,
            "pages": pagination.pages,
            "page": pagination.page,
            "has_next": pagination.has_next,
            "has_prev": pagination.has_prev,
        }
    )


@main_bp.route("/admin/api/approve-all", methods=["POST"])
def ajax_approve_all_notifications():
    """
    AJAX: Approve all pending notifications at once.
    Returns JSON with summary stats.
    """
    pending_notifs = Notification.query.filter_by(status="Pending").all()
    if not pending_notifs:
        return jsonify(
            {"success": False, "message": "No pending notifications to approve."}
        )

    total_approved = len(pending_notifs)
    notif_ids = [n.id for n in pending_notifs]

    for notif in pending_notifs:
        notif.status = "Published"
    db.session.commit()

    total_alerts_sent = 0
    for nid in notif_ids:
        total_alerts_sent += dispatch_alerts(nid)

    return jsonify(
        {
            "success": True,
            "approved": total_approved,
            "alerts_sent": total_alerts_sent,
            "message": f"Approved {total_approved} notifications. {total_alerts_sent} alerts dispatched.",
        }
    )


# --- College CRUD Management Routes ---


@main_bp.route("/admin/colleges")
def admin_colleges():
    """
    Displays a paginated list of organizations in the database with search and filtering.
    """
    page = request.args.get("page", 1, type=int)
    search_q = request.args.get("q", "").strip()
    state_f = request.args.get("state", "").strip()
    type_f = request.args.get("type", "").strip()
    category_f = request.args.get("category", "college").strip()

    if category_f not in ["college", "standalone", "university"]:
        category_f = "college"

    query = Organization.query.filter_by(category=category_f)

    # Apply search query
    if search_q:
        query = query.filter(
            (Organization.name.like(f"%{search_q}%"))
            | (Organization.aishe_code.like(f"%{search_q}%"))
            | (Organization.university_name.like(f"%{search_q}%"))
        )

    # Apply dropdown filters
    if state_f:
        query = query.filter(Organization.state == state_f)
    if type_f and category_f in ["college", "standalone"]:
        query = query.filter(Organization.college_type == type_f)

    # Order alphabetically by name
    query = query.order_by(Organization.name)

    # Paginate (50 per page)
    pagination = query.paginate(page=page, per_page=50, error_out=False)
    colleges = pagination.items

    # Get distinct states for filter
    states = (
        db.session.query(Organization.state)
        .filter(Organization.category == category_f, Organization.state.isnot(None))
        .distinct()
        .order_by(Organization.state)
        .all()
    )
    states = [s[0] for s in states]

    # Get distinct types for filter (only for college and standalone)
    types = []
    if category_f in ["college", "standalone"]:
        types = (
            db.session.query(Organization.college_type)
            .filter(
                Organization.category == category_f,
                Organization.college_type.isnot(None),
            )
            .distinct()
            .order_by(Organization.college_type)
            .all()
        )
        types = [t[0] for t in types]

    return render_template(
        "admin_colleges_list.html",
        colleges=colleges,
        pagination=pagination,
        states=states,
        types=types,
        search_query=search_q,
        selected_state=state_f,
        selected_type=type_f,
        selected_category=category_f,
    )


@main_bp.route("/admin/colleges/create", methods=["GET", "POST"])
def admin_college_create():
    """
    Handles creating a new organization entry (college, standalone, university).
    """
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        aishe_code = request.form.get("aishe_code", "").strip()
        category = request.form.get("category", "college").strip()
        website = request.form.get("website", "").strip()
        state = request.form.get("state", "").strip()
        district = request.form.get("district", "").strip()
        location_type = request.form.get("location_type", "").strip()

        if category not in ["college", "standalone", "university"]:
            category = "college"

        college_type = (
            request.form.get("college_type", "").strip()
            if category in ["college", "standalone"]
            else None
        )
        management = (
            request.form.get("management", "").strip()
            if category in ["college", "standalone"]
            else None
        )
        university_name = (
            request.form.get("university_name", "").strip()
            if category == "college"
            else None
        )

        if not name:
            flash("Organization Name is required!", "error")
            return redirect(url_for("main.admin_college_create"))

        # Check if AISHE code already exists (only if provided)
        if aishe_code:
            existing = Organization.query.filter_by(aishe_code=aishe_code).first()
            if existing:
                flash(
                    f"AISHE Code '{aishe_code}' already exists for: {existing.name}",
                    "error",
                )
                return redirect(url_for("main.admin_college_create"))
        else:
            # Generate a custom ID if blank
            aishe_code = f"TEMP-{random.randint(10000, 99999)}"

        new_college = Organization(
            name=name,
            aishe_code=aishe_code,
            category=category,
            website=website if website else None,
            state=state if state else None,
            district=district if district else None,
            location_type=location_type if location_type else None,
            college_type=college_type if college_type else None,
            management=management if management else None,
            university_name=university_name if university_name else None,
            is_tracked=True,
        )

        db.session.add(new_college)
        db.session.commit()

        flash(f"{category.capitalize()} '{name}' successfully registered!", "success")
        return redirect(url_for("main.admin_colleges", category=category))

    # GET: Load form options from any registered college/standalone/university
    states = (
        db.session.query(Organization.state)
        .filter(
            Organization.category.in_(["college", "standalone", "university"]),
            Organization.state.isnot(None),
        )
        .distinct()
        .order_by(Organization.state)
        .all()
    )
    states = [s[0] for s in states]

    return render_template("admin_college_form.html", college=None, states=states)


@main_bp.route("/admin/colleges/edit/<int:org_id>", methods=["GET", "POST"])
def admin_college_edit(org_id):
    """
    Handles updating an existing organization entry.
    """
    college = Organization.query.get_or_404(org_id)
    if college.category not in ["college", "standalone", "university"]:
        flash(
            "Target record is not a college, standalone, or university organization!",
            "error",
        )
        return redirect(url_for("main.admin_colleges"))

    if request.method == "POST":
        category = request.form.get("category", college.category).strip()
        if category not in ["college", "standalone", "university"]:
            category = college.category

        college.name = request.form.get("name", "").strip()
        college.category = category
        college.website = request.form.get("website", "").strip()
        college.state = request.form.get("state", "").strip()
        college.district = request.form.get("district", "").strip()
        college.location_type = request.form.get("location_type", "").strip()

        if category in ["college", "standalone"]:
            college.college_type = request.form.get("college_type", "").strip()
            college.management = request.form.get("management", "").strip()
        else:
            college.college_type = None
            college.management = None

        if category == "college":
            college.university_name = request.form.get("university_name", "").strip()
        else:
            college.university_name = None

        if not college.name:
            flash("Organization Name is required!", "error")
            return redirect(url_for("main.admin_college_edit", org_id=college.id))

        db.session.commit()
        flash(
            f"{category.capitalize()} '{college.name}' details updated successfully.",
            "success",
        )
        return redirect(url_for("main.admin_colleges", category=category))

    # GET: Load form options
    states = (
        db.session.query(Organization.state)
        .filter(
            Organization.category.in_(["college", "standalone", "university"]),
            Organization.state.isnot(None),
        )
        .distinct()
        .order_by(Organization.state)
        .all()
    )
    states = [s[0] for s in states]

    return render_template("admin_college_form.html", college=college, states=states)


@main_bp.route("/admin/colleges/delete/<int:org_id>", methods=["POST"])
def admin_college_delete(org_id):
    """
    Deletes an organization from the database.
    """
    college = Organization.query.get_or_404(org_id)
    if college.category not in ["college", "standalone", "university"]:
        flash(
            "Record is not a college, standalone, or university organization!", "error"
        )
        return redirect(url_for("main.admin_colleges"))

    name = college.name
    category = college.category
    db.session.delete(college)
    db.session.commit()

    flash(f"{category.capitalize()} '{name}' has been permanently deleted.", "info")
    return redirect(url_for("main.admin_colleges", category=category))


@main_bp.route("/admin/colleges/details/<int:org_id>", methods=["GET"])
def admin_college_details(org_id):
    """
    Renders detailed overview page for a specific college/organization.
    """
    college = Organization.query.get_or_404(org_id)
    if college.category not in ["college", "standalone", "university"]:
        flash(
            "Record is not a college, standalone, or university organization!", "error"
        )
        return redirect(url_for("main.admin_colleges"))

    # Calculate crawl stats
    total_crawls = CrawlerLog.query.filter_by(organization_id=college.id).count()
    success_crawls = CrawlerLog.query.filter_by(
        organization_id=college.id, status="success"
    ).count()
    failed_crawls = CrawlerLog.query.filter_by(
        organization_id=college.id, status="failed"
    ).count()
    success_rate = (
        round((success_crawls / total_crawls * 100), 1) if total_crawls > 0 else 0.0
    )

    # Get notifications
    notifications = (
        Notification.query.filter_by(organization_id=college.id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    total_notifications = len(notifications)

    # Get active subscriptions
    subscriptions = Subscription.query.filter_by(organization_id=college.id).all()
    total_subscriptions = len(subscriptions)

    # Get recent crawl activity logs
    recent_logs = (
        CrawlerLog.query.filter_by(organization_id=college.id)
        .order_by(CrawlerLog.crawled_at.desc())
        .limit(20)
        .all()
    )

    return render_template(
        "admin_college_details.html",
        college=college,
        total_crawls=total_crawls,
        success_crawls=success_crawls,
        failed_crawls=failed_crawls,
        success_rate=success_rate,
        notifications=notifications,
        total_notifications=total_notifications,
        subscriptions=subscriptions,
        total_subscriptions=total_subscriptions,
        recent_logs=recent_logs,
    )


# --- Bulk Scraping & Scheduled Task Manager Routes ---


def calculate_next_run(frequency, base_time=None):
    """
    Calculates next execution time based on frequency string.
    Supports dynamic units: 's' (seconds), 'm' (minutes), 'h' (hours), 'd' (days).
    e.g. '15s', '30m', '2h', '1d'
    """
    if not base_time:
        base_time = datetime.utcnow()

    match = re.match(r"^(\d+)([smhd])$", frequency.strip())
    if not match:
        return base_time + timedelta(hours=1)

    val = int(match.group(1))
    unit = match.group(2)

    if unit == "s":
        return base_time + timedelta(seconds=val)
    elif unit == "m":
        return base_time + timedelta(minutes=val)
    elif unit == "h":
        return base_time + timedelta(hours=val)
    elif unit == "d":
        return base_time + timedelta(days=val)

    return base_time + timedelta(hours=1)


@main_bp.route("/admin/colleges/bulk-scrape", methods=["POST"])
def bulk_scrape_colleges():
    """
    Queues simulated crawls for selected college IDs sequentially in the background.
    """
    data = request.get_json() or {}
    org_ids = data.get("ids", [])
    if not org_ids:
        return jsonify({"success": False, "message": "No colleges selected."}), 400

    from app.workers import scrape_queue, log_to_workers, broadcast_status

    valid_count = 0
    for org_id in org_ids:
        org = Organization.query.get(org_id)
        if org:
            scrape_queue.put((org.id, None))
            valid_count += 1

    log_to_workers(
        f"Bulk scrape request for {valid_count} organizations queued in background.",
        "info",
    )
    broadcast_status()

    return jsonify(
        {
            "success": True,
            "message": f"{valid_count} organizations queued in background for scraping.",
        }
    )


@main_bp.route("/admin/tasks", methods=["GET"])
def admin_tasks():
    """
    Renders crawling task manager with overall statistics.
    """
    tasks = ScheduledTask.query.order_by(ScheduledTask.created_at.desc()).all()
    total_tasks = len(tasks)
    active_tasks = sum(1 for t in tasks if t.status == "Active")
    paused_tasks = total_tasks - active_tasks

    # Fetch distinct states for the task creation dropdown
    states = (
        db.session.query(Organization.state)
        .filter(Organization.category == "college", Organization.state.isnot(None))
        .distinct()
        .order_by(Organization.state)
        .all()
    )
    states = [s[0] for s in states]

    # Pre-filled selected college IDs from query parameter
    selected_ids = request.args.get("selected_ids", "").strip()
    org_id = request.args.get("org_id", "").strip()

    if org_id and not selected_ids:
        selected_ids = org_id

    selected_colleges = []
    if selected_ids:
        try:
            ids = [int(i) for i in selected_ids.split(",") if i.strip()]
            selected_colleges = Organization.query.filter(
                Organization.id.in_(ids)
            ).all()
        except Exception:
            pass

    # Filter tasks list if org_id is specified
    target_org = None
    if org_id:
        try:
            target_org = Organization.query.get(int(org_id))
            if target_org:
                filtered_tasks = []
                for task in tasks:
                    targets = False
                    if task.target_type == "all":
                        targets = True
                    elif (
                        task.target_type == "state"
                        and task.target_query == target_org.state
                    ):
                        targets = True
                    elif task.target_type == "selected":
                        try:
                            ids = [
                                int(i)
                                for i in task.target_query.split(",")
                                if i.strip()
                            ]
                            if target_org.id in ids:
                                targets = True
                        except Exception:
                            pass
                    if targets:
                        filtered_tasks.append(task)
                tasks = filtered_tasks
        except Exception:
            pass

    return render_template(
        "admin_tasks_list.html",
        tasks=tasks,
        total_tasks=total_tasks,
        active_tasks=active_tasks,
        paused_tasks=paused_tasks,
        states=states,
        selected_colleges=selected_colleges,
        selected_ids=selected_ids,
        target_org=target_org,
    )


@main_bp.route("/admin/tasks/create", methods=["POST"])
def admin_task_create():
    """
    Creates a new crawling task.
    """
    name = request.form.get("name", "").strip()
    target_type = request.form.get("target_type", "all")

    freq_val = request.form.get("frequency_val", "1").strip()
    freq_unit = request.form.get("frequency_unit", "h").strip()

    if not name:
        flash("Task name is required!", "error")
        return redirect(url_for("main.admin_tasks"))

    # Validate dynamic frequency values
    if not freq_val.isdigit() or int(freq_val) < 1:
        flash("Frequency value must be a positive integer!", "error")
        return redirect(url_for("main.admin_tasks"))

    if freq_unit not in ["s", "m", "h", "d"]:
        flash("Invalid frequency unit!", "error")
        return redirect(url_for("main.admin_tasks"))

    frequency = f"{freq_val}{freq_unit}"

    target_query = ""
    if target_type == "selected":
        target_query = request.form.get("selected_ids", "").strip()
        if not target_query:
            flash("Please select at least one college for this task.", "error")
            return redirect(url_for("main.admin_tasks"))
    elif target_type == "state":
        target_query = request.form.get("state", "").strip()
        if not target_query:
            flash("Please select a state for this task.", "error")
            return redirect(url_for("main.admin_tasks"))

    next_run = calculate_next_run(frequency)

    task = ScheduledTask(
        name=name,
        frequency=frequency,
        target_type=target_type,
        target_query=target_query,
        status="Active",
        next_run_at=next_run,
    )
    db.session.add(task)
    db.session.commit()

    flash(f"Crawl task '{name}' created successfully.", "success")
    return redirect(url_for("main.admin_tasks"))


@main_bp.route("/admin/tasks/toggle/<int:task_id>", methods=["POST"])
def admin_task_toggle(task_id):
    """
    Pauses or resumes a crawling task.
    """
    task = ScheduledTask.query.get_or_404(task_id)
    if task.status == "Active":
        task.status = "Paused"
        task.next_run_at = None
    else:
        task.status = "Active"
        task.next_run_at = calculate_next_run(task.frequency)

    db.session.commit()
    flash(f"Task '{task.name}' status set to {task.status}.", "success")
    return redirect(url_for("main.admin_tasks"))


@main_bp.route("/admin/tasks/run/<int:task_id>", methods=["POST"])
def admin_task_run(task_id):
    """
    Triggers background execution of a scheduled crawling task.
    """
    task = ScheduledTask.query.get_or_404(task_id)

    # Determine target organizations
    if task.target_type == "all":
        orgs = Organization.query.filter_by(is_tracked=True).all()
    elif task.target_type == "state":
        orgs = Organization.query.filter_by(
            is_tracked=True, state=task.target_query
        ).all()
    elif task.target_type == "selected":
        try:
            ids = [int(i) for i in task.target_query.split(",") if i.strip()]
            orgs = Organization.query.filter(
                Organization.id.in_(ids), Organization.is_tracked
            ).all()
        except Exception:
            orgs = []
    else:
        orgs = []

    if not orgs:
        flash("No tracked organizations found matching the task criteria.", "warning")
        return redirect(url_for("main.admin_tasks"))

    from app.workers import scrape_queue, log_to_workers, broadcast_status

    # Create a ScheduledTaskRun record
    run = ScheduledTaskRun(
        task_id=task.id,
        status="Running",
        trigger_type="Manual",
        started_at=datetime.utcnow(),
        targets_count=len(orgs),
    )
    db.session.add(run)
    db.session.commit()
    run_id = run.id

    for org in orgs:
        scrape_queue.put((org.id, task.id, run_id))

    # Update execution timestamps immediately
    task.last_run_at = datetime.utcnow()
    if task.status == "Active":
        task.next_run_at = calculate_next_run(task.frequency, task.last_run_at)
    db.session.commit()

    log_to_workers(
        f"Scheduled task '{task.name}' triggered manually. Created run #{run_id}. Queuing {len(orgs)} organizations in background.",
        "system",
    )
    broadcast_status()

    flash(
        f"Scheduled task '{task.name}' triggered successfully. Created run #{run_id} and queued {len(orgs)} crawl jobs in background.",
        "success",
    )
    return redirect(url_for("main.admin_tasks"))


@main_bp.route("/admin/tasks/details/<int:task_id>", methods=["GET"])
def admin_task_details(task_id):
    """
    Renders analytics page for a specific task.
    """
    task = ScheduledTask.query.get_or_404(task_id)

    # Query all historical runs for this task
    runs = (
        ScheduledTaskRun.query.filter_by(task_id=task.id)
        .order_by(ScheduledTaskRun.started_at.desc())
        .all()
    )

    selected_run_id = request.args.get("run_id", type=int)
    selected_run = None

    if selected_run_id:
        selected_run = ScheduledTaskRun.query.filter_by(
            id=selected_run_id, task_id=task.id
        ).first_or_404()

        # Calculate metrics for this specific run
        total_crawls = CrawlerLog.query.filter_by(run_id=selected_run.id).count()
        success_crawls = CrawlerLog.query.filter_by(
            run_id=selected_run.id, status="success"
        ).count()
        failed_crawls = CrawlerLog.query.filter_by(
            run_id=selected_run.id, status="failed"
        ).count()
        success_rate = (
            round((success_crawls / total_crawls * 100), 1) if total_crawls > 0 else 0.0
        )

        changes_detected = CrawlerLog.query.filter_by(
            run_id=selected_run.id, detected_changes=True
        ).count()

        notifications = (
            Notification.query.filter_by(run_id=selected_run.id)
            .order_by(Notification.created_at.desc())
            .all()
        )
        total_notifications = len(notifications)

        alerts_sent = (
            DeliveryLog.query.join(Notification)
            .filter(Notification.run_id == selected_run.id)
            .count()
        )

        recent_logs = (
            CrawlerLog.query.filter_by(run_id=selected_run.id)
            .order_by(CrawlerLog.crawled_at.desc())
            .limit(100)
            .all()
        )
    else:
        # Calculate overall metrics across all time for this task
        total_crawls = CrawlerLog.query.filter_by(task_id=task.id).count()
        success_crawls = CrawlerLog.query.filter_by(
            task_id=task.id, status="success"
        ).count()
        failed_crawls = CrawlerLog.query.filter_by(
            task_id=task.id, status="failed"
        ).count()
        success_rate = (
            round((success_crawls / total_crawls * 100), 1) if total_crawls > 0 else 0.0
        )

        changes_detected = CrawlerLog.query.filter_by(
            task_id=task.id, detected_changes=True
        ).count()

        notifications = (
            Notification.query.filter_by(task_id=task.id)
            .order_by(Notification.created_at.desc())
            .all()
        )
        total_notifications = len(notifications)

        alerts_sent = (
            DeliveryLog.query.join(Notification)
            .filter(Notification.task_id == task.id)
            .count()
        )

        # Fetch recent crawl logs (cap at 50 for overall view to prevent performance lag)
        recent_logs = (
            CrawlerLog.query.filter_by(task_id=task.id)
            .order_by(CrawlerLog.crawled_at.desc())
            .limit(50)
            .all()
        )

    # Resolve target organizations
    target_orgs = []
    if task.target_type == "all":
        target_orgs = Organization.query.filter_by(is_tracked=True).limit(20).all()
        target_count = Organization.query.filter_by(is_tracked=True).count()
    elif task.target_type == "state":
        target_orgs = (
            Organization.query.filter_by(is_tracked=True, state=task.target_query)
            .limit(20)
            .all()
        )
        target_count = Organization.query.filter_by(
            is_tracked=True, state=task.target_query
        ).count()
    elif task.target_type == "selected":
        try:
            ids = [int(i) for i in task.target_query.split(",") if i.strip()]
            target_orgs = Organization.query.filter(Organization.id.in_(ids)).all()
            target_count = len(target_orgs)
        except Exception:
            target_count = 0
    else:
        target_count = 0

    return render_template(
        "admin_task_details.html",
        task=task,
        runs=runs,
        selected_run=selected_run,
        selected_run_id=selected_run_id,
        total_crawls=total_crawls,
        success_crawls=success_crawls,
        failed_crawls=failed_crawls,
        success_rate=success_rate,
        changes_detected=changes_detected,
        notifications=notifications,
        total_notifications=total_notifications,
        alerts_sent=alerts_sent,
        recent_logs=recent_logs,
        target_orgs=target_orgs,
        target_count=target_count,
    )


@main_bp.route("/admin/tasks/delete/<int:task_id>", methods=["POST"])
def admin_task_delete(task_id):
    """
    Deletes a scheduled crawling task, nullifying task_id references in logs/notifications first.
    """
    task = ScheduledTask.query.get_or_404(task_id)
    name = task.name

    # Nullify references in linked records to prevent key/integrity errors
    CrawlerLog.query.filter_by(task_id=task.id).update({CrawlerLog.task_id: None})
    Notification.query.filter_by(task_id=task.id).update({Notification.task_id: None})

    db.session.delete(task)
    db.session.commit()

    flash(f"Task '{name}' has been deleted.", "info")
    return redirect(url_for("main.admin_tasks"))


# ══════════════════════════════════════════════════════════════════════════════
#  SETTINGS PAGE — AI Provider Switching & Full Codebase Configuration
# ══════════════════════════════════════════════════════════════════════════════


@main_bp.route("/admin/settings")
def admin_settings():
    """
    Renders the centralised settings page with all current configuration values.
    """
    settings = get_all_settings()
    return render_template("settings.html", settings=settings)


@main_bp.route("/admin/settings", methods=["POST"])
def admin_settings_save():
    """
    Saves all settings submitted from the settings form.
    """
    # AI Provider
    set_setting("ai_provider", request.form.get("ai_provider", "none"))

    # Gemini
    set_setting("gemini_api_key", request.form.get("gemini_api_key", ""))
    set_setting("gemini_model", request.form.get("gemini_model", "gemini-2.5-flash"))

    # Ollama
    set_setting("ollama_host", request.form.get("ollama_host", "http://localhost:11434"))
    set_setting("ollama_model", request.form.get("ollama_model", "gemma2"))

    # Notification & content workflow (checkboxes: absent = 'false')
    set_setting(
        "auto_approve_notifications",
        "true" if request.form.get("auto_approve_notifications") else "false",
    )
    set_setting(
        "content_generation_enabled",
        "true" if request.form.get("content_generation_enabled") else "false",
    )
    set_setting(
        "alert_dispatch_enabled",
        "true" if request.form.get("alert_dispatch_enabled") else "false",
    )

    # Scraper tuning
    set_setting("scraper_timeout", request.form.get("scraper_timeout", "12"))
    set_setting(
        "scraper_user_agent",
        request.form.get("scraper_user_agent", SETTING_DEFAULTS["scraper_user_agent"]),
    )
    set_setting(
        "llm_html_char_limit", request.form.get("llm_html_char_limit", "18000")
    )

    flash("All settings saved successfully.", "success")
    return redirect(url_for("main.admin_settings"))


@main_bp.route("/admin/settings/reset", methods=["POST"])
def admin_settings_reset():
    """
    Resets all settings to their defaults.
    """
    reset_all_settings()
    flash("All settings have been reset to defaults.", "info")
    return redirect(url_for("main.admin_settings"))


@main_bp.route("/admin/settings/test-ollama", methods=["POST"])
def admin_test_ollama():
    """
    AJAX: Tests connectivity to an Ollama instance and returns available models.
    """
    data = request.get_json(silent=True) or {}
    host = data.get("host", "http://localhost:11434")
    result = AIEngine.test_ollama_connection(host)
    return jsonify(result)


@main_bp.route("/admin/settings/test-gemini", methods=["POST"])
def admin_test_gemini():
    """
    AJAX: Tests a Gemini API key validity.
    """
    data = request.get_json(silent=True) or {}
    api_key = data.get("api_key", "")
    if not api_key:
        return jsonify({"success": False, "error": "No API key provided."})
    result = AIEngine.test_gemini_connection(api_key)
    return jsonify(result)
