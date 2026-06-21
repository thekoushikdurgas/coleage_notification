<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Can you break the technical tasks in phases

Here’s a concrete phase‑wise breakdown focused on *technical* tasks you’d actually implement.

***

## Phase 1 – Core domain, storage, and APIs

Goal: Get a clean core model + APIs before touching scrapers.[^1]

- Design the domain model: `Organization` (college/board/regulator), `Notification`, `NotificationType` (admission, exam, result, policy, scholarship, etc.), and `Source` metadata (URL, type, frequency).[^1]
- Add fields required by the spec: admission dates, registration dates, exam/counselling dates, merit list dates, fee/scholarship/seat matrix updates, eligibility changes, etc. for college notifications.[^1]
- Add fields for board data: result notifications, exam schedule/date sheet, admit card updates, revaluation/supplementary notices, registration/marksheet updates, circulars, academic calendar and general board announcements.[^1]
- Add fields for regulator data: notifications, circulars, public notices, approvals, new regulations, policy changes, scholarships, accreditation and ranking updates.[^1]
- Implement CRUD + query APIs for notifications (filter by organization, type, date range, status) that the admin UI, public site and alert engine will consume.[^1]

***

## Phase 2 – Source registry and scraper framework

Goal: Build a generic scraping/monitoring framework and onboard a few pilot sources.[^1]

- Create a `Source` registry listing all categories:
    - Colleges: IIT, NIT, IIIT, IIM, central universities, state universities, government/private universities, medical and engineering colleges.[^1]
    - Boards: CBSE, CISCE and state boards (UP, Rajasthan, MP, Haryana, Punjab, Maharashtra, Karnataka, Tamil Nadu, Telangana, Andhra Pradesh, Kerala, etc.).[^1]
    - Regulators: AICTE, UGC, NTA, Ministry of Education, NMC, DCI, PCI, BCI, NCTE, NAAC, NBA, AIU, NCERT and education ministry notifications.[^1]
- Implement a pluggable scraper framework: per‑source configuration (URL, selectors, pagination, date parsing rules), shared HTTP client, retries, robots handling.
- Implement 30‑minute polling (cron, Celery beat, Temporal, etc.) for each source as required in “automatic scraping every 30 minutes” and “real‑time monitoring.”[^1]
- Implement change detection: hash content or last‑seen IDs per source to determine when a new notification appears or existing one is updated.
- Map raw scraped fields into the core `Notification` model: titles, dates, URLs, and status (e.g., Active/Closed as in the IIT Delhi and CBSE examples).[^1]

***

## Phase 3 – Normalization, deduplication, and tagging pipeline

Goal: Convert messy raw records into clean, enriched notifications ready for content + alerts.[^1]

- Introduce an ingestion queue/topic between scrapers and the core system (e.g., SQS/Kafka) to decouple scraping from processing.
- Build a normalization service that:
    - Parses and normalizes dates (application start/end, registration start/last date, exam dates, counselling dates, merit list dates, etc.).[^1]
    - Standardizes notification categories (admission, exam date, result, scholarship, policy update, etc.) based on patterns in the text.[^1]
- Implement AI/heuristic‑based duplicate detection as required (“AI‑based duplicate detection”): title similarity, embedding similarity, same organization + overlapping date ranges, etc.[^1]
- Implement tagging logic: tag each notification by course, college, exam, state, board and notification type as specified.[^1]
- Persist both raw and normalized versions (for audit/debugging) and expose a “normalized notifications” API for downstream modules.

***

## Phase 4 – AI content generation service

Goal: Turn structured notifications into SEO‑ready content and messaging copy.[^1]

- Define prompt templates per notification type for generating:
    - News article describing the event (admission, exam, result, policy, etc.).
    - Meta title and meta description.[^1]
    - SEO‑friendly URL/slug.[^1]
    - Social media caption.[^1]
    - WhatsApp/Telegram message.[^1]
    - Push notification text.[^1]
- Implement a content generation microservice triggered when a new normalized notification is created or updated (e.g., via event bus).
- Store generated content in a separate `Content` entity linked to `Notification` (supports regeneration if rules change).
- Add basic quality checks: ensure dates/links in generated text are consistent with structured fields (e.g., “JEE Advanced 2027 registration begins, check dates, eligibility, fees, direct link”).[^1]
- Expose APIs for the web frontend to render SEO pages and for admin to review/edit generated content before publishing (optional approval workflow).

***

## Phase 5 – Admin dashboard and moderation workflow

Goal: Give admins control, visibility, and search over the notification universe.[^1]

- Build an admin UI that surfaces:
    - “Total notifications today,” “Total colleges tracked,” “Total boards tracked,” “Total regulatory updates,” and “Trending notifications” stats as specified.[^1]
- Implement filters: by state, college, course, exam, board, notification type, and time range.[^1]
- Implement global search across all notifications (by title, organization, type, content body).[^1]
- Add moderation workflow:
    - Statuses like Draft → Pending Review → Approved → Published.
    - Option to auto‑publish (skip review) as allowed by “admin approval workflow (optional).”[^1]
- Add ability to manually create/edit notifications and override scraper data if official sites are inconsistent.

***

## Phase 6 – Subscription engine and multi‑channel alert delivery

Goal: Deliver personalized, real‑time alerts over multiple channels.[^1]

- Implement subscription model where users can subscribe by: college, exam, course, state, and board as required.[^1]
- Define matching rules: on `Notification` attributes (org, type, state, course/exam tags) to find which users should receive a given notification.
- Implement channel adapters:
    - Email (SMTP or transactional provider).
    - WhatsApp (Business API).
    - Telegram (bot API).
    - Push notifications (web/app push).
    - SMS via an SMS gateway.[^1]
- Build a notification dispatcher service that, upon a `Notification` being published, resolves matching subscribers and pushes the correct template per channel (using generated WhatsApp/Telegram/push content from Phase 4).[^1]
- Implement rate limiting, retry, dead‑letter queues and delivery logs (`DeliveryLog`) per user/channel for reliability and debugging.

***

## Phase 7 – SEO, performance, and scale‑out

Goal: Hit the SEO and growth objectives and ensure system resilience.[^1]

- Implement SEO‑friendly routing and page templates so each notification/content pair becomes a unique indexable page, supporting the “500–1000 new indexed pages monthly” goal.[^1]
- Implement sitemaps and structured data (e.g., events, courses, exams) to improve “Google Discover visibility” and rankings for admission‑related keywords.[^1]
- Add caching and query optimization for frequently accessed lists like “real‑time admission updates” and “trending notifications.”[^1]
- Add monitoring/alerting for scrapers (per‑source failure rate, lag), ingestion pipeline throughput, content generation failures, and alert‑delivery success rates.
- Gradually onboard all remaining colleges, boards, and regulators from the requirement list until coverage is complete.[^1]

***

If you tell me your target stack (e.g., FastAPI + Postgres + Redis + Celery/Kafka + Next.js), I can map each phase to specific services, DB tables, and background jobs so you can turn this into an implementation checklist or Jira epics.

<div align="center">⁂</div>

[^1]: FormsADDA-Website-Enhancement-Real-Time-Notification-System-Requirement-Document-1-1.pdf

