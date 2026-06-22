import threading
import queue
import time
import json
import traceback
import re
from datetime import datetime, timedelta
from app.database import (
    db,
    Organization,
    Notification,
    CrawlerLog,
    ScheduledTask,
    ScheduledTaskRun,
    SystemSetting,
)
from app.scraper import ScraperEngine
from app.ai_engine import AIEngine
from typing import Tuple, Optional

# Queues with type annotations
scrape_queue: queue.Queue[Tuple[int, Optional[int], Optional[int]]] = queue.Queue()
scraped_queue: queue.Queue[Tuple[int, Optional[int], Optional[int], dict]] = queue.Queue()

# Status Tracking
scraper_status = {"status": "Idle", "target": ""}
loader_status = {"status": "Idle", "target": ""}

# SSE Client Listeners
sse_listeners: list[queue.Queue] = []
listeners_lock = threading.Lock()


def double_frequency(frequency):
    """
    Doubles the frequency interval. e.g., '30s' -> '60s', '1h' -> '2h'.
    """
    match = re.match(r"^(\d+)([smhd])$", frequency.strip())
    if not match:
        return frequency
    val = int(match.group(1))
    unit = match.group(2)
    return f"{val * 2}{unit}"


def calculate_next_run(frequency, base_time=None):
    """
    Calculates next execution time based on frequency string.
    Supports units: 's' (seconds), 'm' (minutes), 'h' (hours), 'd' (days).
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


def broadcast_sse(event_type, payload):
    """
    Broadcasts a JSON event to all registered SSE clients.
    """
    payload_data = {"type": event_type, "data": payload}
    with listeners_lock:
        for q in sse_listeners:
            try:
                q.put_nowait(payload_data)
            except queue.Full:
                pass


def log_to_workers(message, log_type="info"):
    """
    Utility to print to logs and broadcast live log lines to SSE listeners.
    """
    now_str = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{log_type.upper()}] {message}"
    print(f"[{now_str}] {formatted}")
    broadcast_sse("log", {"message": message, "log_type": log_type})


def broadcast_status():
    """
    Broadcasts worker statuses and current queue lengths to SSE listeners.
    """
    status_payload = {
        "scraper": scraper_status,
        "loader": loader_status,
        "scrape_queue_size": scrape_queue.qsize(),
        "scraped_queue_size": scraped_queue.qsize(),
        "total_backlog": scrape_queue.qsize() + scraped_queue.qsize(),
    }
    broadcast_sse("status", status_payload)


def save_and_broadcast_crawler_log(
    org_id,
    status,
    detected_changes=False,
    error_message=None,
    task_id=None,
    run_id=None,
):
    """
    Creates and saves a CrawlerLog to the database, and broadcasts a 'crawler_log' event.
    """
    org = Organization.query.get(org_id)
    org_name = org.name if org else "Unknown Organization"

    log = CrawlerLog(
        organization_id=org_id,
        status=status,
        detected_changes=detected_changes,
        error_message=error_message,
        task_id=task_id,
        run_id=run_id,
    )
    db.session.add(log)
    db.session.commit()

    # Broadcast to SSE
    log_payload = {
        "id": log.id,
        "organization_name": org_name,
        "status": status,
        "detected_changes": detected_changes,
        "error_message": error_message,
        "crawled_at": datetime.now().strftime("%I:%M:%S %p"),
    }
    broadcast_sse("crawler_log", log_payload)
    return log


def check_run_completion(run_id):
    """
    Checks if a scheduled task run has finished all its targets.
    If so, updates its status to 'Completed' and calculates success/failure counts.
    """
    try:
        run = ScheduledTaskRun.query.get(run_id)
        if not run:
            return

        if run.status == "Completed":
            return

        processed_count = CrawlerLog.query.filter_by(run_id=run_id).count()
        if processed_count >= run.targets_count:
            # Complete the run
            run.status = "Completed"
            run.completed_at = datetime.utcnow()

            # Aggregate stats
            successes = CrawlerLog.query.filter_by(
                run_id=run_id, status="success"
            ).count()
            failures = CrawlerLog.query.filter_by(
                run_id=run_id, status="failed"
            ).count()
            notifs = Notification.query.filter_by(run_id=run_id).count()

            run.success_count = successes
            run.failed_count = failures
            run.notifications_count = notifs

            db.session.commit()
            log_to_workers(
                f"Scheduled task run #{run.id} for '{run.scheduled_task.name}' completed. Status: {run.status}, Success: {successes}, Failures: {failures}, Notifications: {notifs}",
                "system",
            )

            # --- Dynamic Schedule Scaling (Backoff / Restoral) ---
            task = run.scheduled_task
            if task and run.targets_count > 0:
                non_dup_count = Notification.query.filter_by(
                    run_id=run_id
                ).filter(~Notification.is_duplicate).count()
                if non_dup_count == 0:
                    # All websites had no update or were duplicates! Double the frequency interval.
                    original_freq = task.frequency
                    if not task.base_frequency:
                        task.base_frequency = original_freq

                    new_freq = double_frequency(original_freq)
                    if new_freq != original_freq:
                        task.frequency = new_freq
                        # Recalculate next run based on last_run_at
                        if task.status == "Active" and task.last_run_at:
                            task.next_run_at = calculate_next_run(
                                task.frequency, task.last_run_at
                            )

                        db.session.commit()
                        log_to_workers(
                            f"Task '{task.name}' backed off (no updates/duplicates). Frequency increased from {original_freq} to {task.frequency}. Next run scheduled at {task.next_run_at}.",
                            "system",
                        )
                else:
                    # At least one website had a new non-duplicate notification! Restore base frequency.
                    if task.base_frequency:
                        old_freq = task.frequency
                        task.frequency = task.base_frequency
                        task.base_frequency = None

                        if task.status == "Active" and task.last_run_at:
                            task.next_run_at = calculate_next_run(
                                task.frequency, task.last_run_at
                            )

                        db.session.commit()
                        log_to_workers(
                            f"Task '{task.name}' received new announcements. Restored frequency from {old_freq} back to base frequency {task.frequency}. Next run scheduled at {task.next_run_at}.",
                            "system",
                        )
            # ----------------------------------------------------

            broadcast_status()
    except Exception as e:
        print(f"Error checking run completion: {e}")
        traceback.print_exc()


class ScraperWorker(threading.Thread):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.daemon = True
        self.running = True

    def run(self):
        log_to_workers("Scraper Worker initialized.", "system")
        while self.running:
            try:
                # Dequeue next task (timeout of 1s to allow thread shutdown check)
                item = scrape_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if len(item) == 3:
                org_id, task_id, run_id = item
            else:
                org_id, task_id = item
                run_id = None

            with self.app.app_context():
                org = Organization.query.get(org_id)
                if not org:
                    log_to_workers(
                        f"Organization ID {org_id} not found in database.", "error"
                    )
                    scrape_queue.task_done()
                    continue

                org_name = org.name

            # Update Status
            scraper_status["status"] = "Active"
            scraper_status["target"] = org_name
            broadcast_status()

            log_to_workers(
                f"Starting simulated scrape for college: {org_name}", "system"
            )

            try:
                # Simulate scrape (independent of DB session context)
                with self.app.app_context():
                    scraped_data = ScraperEngine.simulate_scrape(org_id)

                if scraped_data:
                    log_to_workers(
                        f"Successfully scraped '{scraped_data['title'][:40]}...'. Passing to Loader Worker.",
                        "success",
                    )
                    scraped_queue.put((org_id, task_id, run_id, scraped_data))
                else:
                    log_to_workers(
                        f"Crawl completed for '{org_name}'. No new notices found.",
                        "info",
                    )
                    with self.app.app_context():
                        save_and_broadcast_crawler_log(
                            org_id=org_id,
                            status="success",
                            detected_changes=False,
                            task_id=task_id,
                            run_id=run_id,
                        )
                        if run_id:
                            check_run_completion(run_id)
            except Exception as e:
                log_to_workers(f"Scraper error for '{org_name}': {str(e)}", "error")
                traceback.print_exc()
                with self.app.app_context():
                    save_and_broadcast_crawler_log(
                        org_id=org_id,
                        status="failed",
                        error_message=str(e),
                        task_id=task_id,
                        run_id=run_id,
                    )
                    if run_id:
                        check_run_completion(run_id)

            # Clear Status
            scraper_status["status"] = "Idle"
            scraper_status["target"] = ""
            broadcast_status()
            scrape_queue.task_done()


class LoaderWorker(threading.Thread):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.daemon = True
        self.running = True

    def run(self):
        log_to_workers("Loader Worker initialized.", "system")
        while self.running:
            # 1. Fetch a batch of items
            items = []
            try:
                # Block for up to 1.0 seconds to get the first item
                item = scraped_queue.get(timeout=1.0)
                items.append(item)

                # Fetch up to 49 more items non-blocking (immediate dequeue)
                while len(items) < 50:
                    try:
                        item = scraped_queue.get_nowait()
                        items.append(item)
                    except queue.Empty:
                        break
            except queue.Empty:
                continue

            # 2. Process the batch in a single app context and single database transaction
            with self.app.app_context():
                try:
                    # Cache auto-approve setting for the batch
                    auto_approve = False
                    setting = SystemSetting.query.filter_by(
                        key="auto_approve_notifications"
                    ).first()
                    if setting and setting.value == "true":
                        auto_approve = True

                    logs_to_broadcast = []
                    notifications_to_broadcast = []

                    for item in items:
                        if len(item) == 4:
                            org_id, task_id, run_id, scraped_data = item
                        else:
                            org_id, task_id, scraped_data = item
                            run_id = None

                        org = Organization.query.get(org_id)
                        if not org:
                            log_to_workers(
                                f"Loader error: Org ID {org_id} not found.", "error"
                            )
                            continue

                        org_name = org.name

                        # Update status for currently processing item
                        loader_status["status"] = "Active"
                        loader_status["target"] = scraped_data["title"]
                        broadcast_status()

                        log_to_workers(
                            f"Processing and loading announcement to DB: '{scraped_data['title'][:50]}...'",
                            "system",
                        )

                        # A. Check if this exact title has already been ingested for this org
                        existing = Notification.query.filter_by(
                            organization_id=org_id, title=scraped_data["title"]
                        ).first()

                        if existing:
                            log_to_workers(
                                f"Notice already exists in database. Skipping duplicate save.",
                                "info",
                            )
                            log = CrawlerLog(
                                organization_id=org_id,
                                status="success",
                                detected_changes=False,
                                task_id=task_id,
                                run_id=run_id,
                            )
                            db.session.add(log)
                            logs_to_broadcast.append(
                                {
                                    "org_id": org_id,
                                    "org_name": org_name,
                                    "status": "success",
                                    "detected_changes": False,
                                    "error_message": None,
                                    "task_id": task_id,
                                    "run_id": run_id,
                                }
                            )
                        else:
                            # B. Run duplicate detection
                            is_dup, dup_id = ScraperEngine.detect_duplicate(
                                scraped_data["title"], org_id
                            )

                            # C. Create and save new notification
                            new_notif = Notification(
                                organization_id=org_id,
                                title=scraped_data["title"],
                                body=scraped_data["body"],
                                category=scraped_data["category"],
                                source_url=scraped_data["source_url"],
                                is_duplicate=is_dup,
                                duplicate_of_id=dup_id,
                                status=(
                                    "Duplicate"
                                    if is_dup
                                    else ("Published" if auto_approve else "Pending")
                                ),
                                task_id=task_id,
                                run_id=run_id,
                            )
                            db.session.add(new_notif)
                            db.session.flush()  # Populate ID

                            # D. AI extraction and content generation ONLY IF NOT duplicate
                            if not is_dup:
                                AIEngine.extract_dates_and_details(new_notif.id)
                                api_key = self.app.config.get("GEMINI_API_KEY")
                                AIEngine.generate_content(new_notif.id, api_key=api_key)

                                # If auto-approved, dispatch alerts
                                alerts_sent = 0
                                if auto_approve:
                                    from app.routes import dispatch_alerts

                                    alerts_sent = dispatch_alerts(new_notif.id)
                                    log_msg = f"Successfully auto-approved notification (ID: {new_notif.id}) for {org_name}. {alerts_sent} alerts sent."
                                else:
                                    log_msg = f"Successfully loaded notification (ID: {new_notif.id}) for {org_name} to database."

                                if new_notif.status == "Pending":
                                    notifications_to_broadcast.append(
                                        {
                                            "id": new_notif.id,
                                            "title": new_notif.title,
                                            "category": new_notif.category,
                                            "organization_name": org_name,
                                            "created_at": new_notif.created_at,
                                        }
                                    )
                            else:
                                log_msg = f"Duplicate notice saved (ID: {new_notif.id}) for {org_name}. Skipping AI content generation."

                            log_to_workers(log_msg, "success")

                            # E. Create crawler log
                            log = CrawlerLog(
                                organization_id=org_id,
                                status="success",
                                detected_changes=True,
                                task_id=task_id,
                                run_id=run_id,
                            )
                            db.session.add(log)
                            logs_to_broadcast.append(
                                {
                                    "org_id": org_id,
                                    "org_name": org_name,
                                    "status": "success",
                                    "detected_changes": True,
                                    "error_message": None,
                                    "task_id": task_id,
                                    "run_id": run_id,
                                }
                            )

                    # Commit the entire batch!
                    db.session.commit()

                    # F. Broadcast logs and notifications AFTER commit
                    for log_info in logs_to_broadcast:
                        log_payload = {
                            "organization_name": log_info["org_name"],
                            "status": log_info["status"],
                            "detected_changes": log_info["detected_changes"],
                            "error_message": log_info["error_message"],
                            "crawled_at": datetime.now().strftime("%I:%M:%S %p"),
                        }
                        broadcast_sse("crawler_log", log_payload)
                        if log_info["run_id"]:
                            check_run_completion(log_info["run_id"])

                    for notif_info in notifications_to_broadcast:
                        notif_payload = {
                            "id": notif_info["id"],
                            "title": notif_info["title"],
                            "category": notif_info["category"],
                            "organization_name": notif_info["organization_name"],
                            "created_at": notif_info["created_at"].strftime(
                                "%I:%M:%S %p"
                            ),
                        }
                        broadcast_sse("notification", notif_payload)

                except Exception as batch_error:
                    db.session.rollback()
                    log_to_workers(
                        f"Batch processing error: {str(batch_error)}. Falling back to individual processing.",
                        "error",
                    )
                    traceback.print_exc()

                    # Fallback: process each item individually
                    for item in items:
                        if len(item) == 4:
                            org_id, task_id, run_id, scraped_data = item
                        else:
                            org_id, task_id, scraped_data = item
                            run_id = None

                        try:
                            org = Organization.query.get(org_id)
                            org_name = org.name if org else "Unknown"

                            existing = Notification.query.filter_by(
                                organization_id=org_id, title=scraped_data["title"]
                            ).first()

                            if existing:
                                log = CrawlerLog(
                                    organization_id=org_id,
                                    status="success",
                                    detected_changes=False,
                                    task_id=task_id,
                                    run_id=run_id,
                                )
                                db.session.add(log)
                                db.session.commit()
                                save_and_broadcast_crawler_log(
                                    org_id=org_id,
                                    status="success",
                                    detected_changes=False,
                                    task_id=task_id,
                                    run_id=run_id,
                                )
                            else:
                                is_dup, dup_id = ScraperEngine.detect_duplicate(
                                    scraped_data["title"], org_id
                                )
                                new_notif = Notification(
                                    organization_id=org_id,
                                    title=scraped_data["title"],
                                    body=scraped_data["body"],
                                    category=scraped_data["category"],
                                    source_url=scraped_data["source_url"],
                                    is_duplicate=is_dup,
                                    duplicate_of_id=dup_id,
                                    status=(
                                        "Duplicate"
                                        if is_dup
                                        else (
                                            "Published" if auto_approve else "Pending"
                                        )
                                    ),
                                    task_id=task_id,
                                    run_id=run_id,
                                )
                                db.session.add(new_notif)
                                db.session.flush()

                                if not is_dup:
                                    AIEngine.extract_dates_and_details(new_notif.id)
                                    api_key = self.app.config.get("GEMINI_API_KEY")
                                    AIEngine.generate_content(
                                        new_notif.id, api_key=api_key
                                    )

                                    if auto_approve:
                                        from app.routes import dispatch_alerts

                                        dispatch_alerts(new_notif.id)

                                    if new_notif.status == "Pending":
                                        broadcast_sse(
                                            "notification",
                                            {
                                                "id": new_notif.id,
                                                "title": new_notif.title,
                                                "category": new_notif.category,
                                                "organization_name": org_name,
                                                "created_at": new_notif.created_at.strftime(
                                                    "%I:%M:%S %p"
                                                ),
                                            },
                                        )

                                db.session.commit()
                                save_and_broadcast_crawler_log(
                                    org_id=org_id,
                                    status="success",
                                    detected_changes=True,
                                    task_id=task_id,
                                    run_id=run_id,
                                )

                            if run_id:
                                check_run_completion(run_id)
                        except Exception as ind_error:
                            db.session.rollback()
                            log_to_workers(
                                f"Individual fallback error for '{org_name}': {str(ind_error)}",
                                "error",
                            )
                            save_and_broadcast_crawler_log(
                                org_id=org_id,
                                status="failed",
                                error_message=str(ind_error),
                                task_id=task_id,
                                run_id=run_id,
                            )
                            if run_id:
                                check_run_completion(run_id)

            # Clear Status
            loader_status["status"] = "Idle"
            loader_status["target"] = ""
            broadcast_status()
            for _ in items:
                scraped_queue.task_done()


class SchedulerWorker(threading.Thread):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.daemon = True
        self.running = True

    def run(self):
        log_to_workers("Scheduler Worker initialized.", "system")
        while self.running:
            # Poll every 5 seconds
            time.sleep(5.0)

            try:
                with self.app.app_context():
                    now = datetime.utcnow()
                    # Query active tasks that are due
                    due_tasks = ScheduledTask.query.filter(
                        ScheduledTask.status == "Active",
                        ScheduledTask.next_run_at <= now,
                    ).all()

                    for task in due_tasks:
                        # Determine target organizations
                        if task.target_type == "all":
                            orgs = Organization.query.filter_by(is_tracked=True).all()
                        elif task.target_type == "state":
                            orgs = Organization.query.filter_by(
                                is_tracked=True, state=task.target_query
                            ).all()
                        elif task.target_type == "selected":
                            try:
                                ids = [
                                    int(i)
                                    for i in task.target_query.split(",")
                                    if i.strip()
                                ]
                                orgs = Organization.query.filter(
                                    Organization.id.in_(ids),
                                    Organization.is_tracked,
                                ).all()
                            except Exception:
                                orgs = []
                        else:
                            orgs = []

                        # Create ScheduledTaskRun record
                        run = ScheduledTaskRun(
                            task_id=task.id,
                            status="Running" if orgs else "Completed",
                            trigger_type="Auto",
                            started_at=now,
                            completed_at=None if orgs else now,
                            targets_count=len(orgs),
                        )
                        db.session.add(run)
                        db.session.commit()  # Commit to get run.id
                        run_id = run.id

                        if orgs:
                            log_to_workers(
                                f"Scheduler: Task '{task.name}' is due. Created run #{run_id}. Queuing {len(orgs)} organizations in background.",
                                "system",
                            )

                            # Queue all organizations with run_id
                            for org in orgs:
                                scrape_queue.put((org.id, task.id, run_id))

                            # Update task run times
                            task.last_run_at = now
                            task.next_run_at = calculate_next_run(task.frequency, now)
                            db.session.commit()

                            # Broadcast updated pipeline status
                            broadcast_status()
                        else:
                            # No orgs matched, just reschedule to avoid spinning on it
                            task.last_run_at = now
                            task.next_run_at = calculate_next_run(task.frequency, now)
                            db.session.commit()
                            log_to_workers(
                                f"Scheduler: Task '{task.name}' is due. Created run #{run_id} (0 targets matched). Rescheduled.",
                                "info",
                            )
            except Exception as e:
                print(f"Scheduler Worker error: {e}")
                traceback.print_exc()


def start_workers(app):
    """
    Starts background scraper, loader, and scheduler workers.
    """
    scraper = ScraperWorker(app)
    scraper.start()

    loader = LoaderWorker(app)
    loader.start()

    scheduler = SchedulerWorker(app)
    scheduler.start()
