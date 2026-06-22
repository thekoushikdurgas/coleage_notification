"""
scraper.py — Real web scraping engine with LLM-assisted adaptive selector recovery.

Flow for each organization:
  1. Fetch HTML from org.website using requests
  2. Load CollegeScrapeConfig from DB (stored CSS selectors)
     → if none, seed with DEFAULT_SELECTORS
  3. Try every stored selector via BeautifulSoup
     → Found items → return them, update health to "ok"
  4. Selectors all failed → call Gemini LLM with the raw HTML
     → LLM returns new selectors → save to DB, re-extract, return
     → LLM says nothing found → raise SelectorLostError (admin alert)
  5. SelectorLostError is caught in workers.py → CrawlerLog status="selector_lost"

The legacy simulate_scrape() is preserved as simulate_scrape_legacy()
for orgs with no website or when HTTP fetch fails.
"""

import json
import random
import difflib
import urllib.request
import urllib.error
import re
from datetime import datetime
from typing import Optional

from app.database import db, Organization, Notification, CrawlerLog, CollegeScrapeConfig
from app.scrape_defaults import get_default_selectors
from app.settings_helper import get_setting

# ─── Optional dependencies (graceful degradation) ────────────────────────────
try:
    import requests  # type: ignore[import]
    from bs4 import BeautifulSoup  # type: ignore[import]

    SCRAPING_AVAILABLE = True
except ImportError:
    SCRAPING_AVAILABLE = False
    print(
        "[WARN] scraper.py: 'requests' or 'beautifulsoup4' not installed. "
        "Real scraping is disabled — using simulation fallback. "
        "Install with: pip install requests beautifulsoup4"
    )

# ─── HTTP fetch settings ─────────────────────────────────────────────────────
DEFAULT_TIMEOUT = 12  # seconds
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

# Maximum chars of HTML to send to LLM (keep token costs low)
LLM_HTML_CHAR_LIMIT = 18_000

# Minimum text length for a scraped title to be considered valid
MIN_TITLE_LENGTH = 8


# ─── Custom exceptions ───────────────────────────────────────────────────────
class SelectorLostError(Exception):
    """Raised when neither stored selectors nor LLM could find notifications."""


class FetchError(Exception):
    """Raised when the website could not be fetched."""


# ─────────────────────────────────────────────────────────────────────────────
#  RealScraperEngine
# ─────────────────────────────────────────────────────────────────────────────
class RealScraperEngine:
    """
    Handles real HTTP fetching, CSS-selector-based extraction, and
    LLM-assisted selector recovery for a given Organization.
    """

    # ── Step 1: Fetch ─────────────────────────────────────────────────────────
    @staticmethod
    def fetch_html(url: str) -> str:
        """
        Fetches raw HTML from the given URL.
        Returns the HTML text string.
        Raises FetchError on any network or HTTP problem.
        """
        if not SCRAPING_AVAILABLE:
            raise FetchError("requests/beautifulsoup4 not installed")

        # Ensure URL has a scheme
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            timeout_val = int(get_setting("scraper_timeout", "12"))
            user_agent = get_setting(
                "scraper_user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            headers = {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9",
            }
            
            resp = requests.get(
                url,
                headers=headers,
                timeout=timeout_val,
                allow_redirects=True,
            )
            resp.raise_for_status()
            # Try UTF-8, fall back to detected encoding
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.exceptions.Timeout:
            raise FetchError(f"Timeout after {timeout_val}s fetching {url}")
        except requests.exceptions.ConnectionError as e:
            raise FetchError(f"Connection error fetching {url}: {e}")
        except requests.exceptions.HTTPError as e:
            raise FetchError(f"HTTP error fetching {url}: {e}")
        except Exception as e:
            raise FetchError(f"Unexpected error fetching {url}: {e}")

    # ── Step 2: Extract with a single selector config ─────────────────────────
    @staticmethod
    def _extract_with_selector(html: str, selector_cfg: dict) -> list:
        """
        Applies one selector config to BeautifulSoup-parsed HTML.
        Returns a list of notification dicts: [{title, link, date_hint}]
        Returns empty list if nothing useful is found.
        """
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select(selector_cfg["css"])
        results = []

        for item in items:
            # ── Extract title ──────────────────────────────────────────────
            title_attr = selector_cfg.get("title_attr", "text")
            if title_attr == "text":
                title = item.get_text(separator=" ", strip=True)
            elif title_attr == "title":
                title = item.get("title", "").strip()
            elif title_attr == "alt":
                title = item.get("alt", "").strip()
            else:
                title = item.get_text(separator=" ", strip=True)

            # Clean excessive whitespace
            title = re.sub(r"\s+", " ", title).strip()

            # Skip items with very short or empty titles
            if len(title) < MIN_TITLE_LENGTH:
                continue

            # Skip items that look like header rows (all-caps or tiny)
            if title.isupper() and len(title) < 20:
                continue

            # ── Extract link ───────────────────────────────────────────────
            link_tag = selector_cfg.get("link_tag")
            link = None
            if link_tag is None:
                # The item itself might be an <a>
                if item.name == "a":
                    link = item.get("href", "")
                else:
                    a = item.find("a")
                    link = a.get("href", "") if a else None
            else:
                a = item.select_one(link_tag)
                link = a.get("href", "") if a else None

            # ── Extract date hint (best-effort) ────────────────────────────
            date_hint = None
            # Look for a <span> or <small> that contains a date-like pattern
            date_pattern = re.compile(
                r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
                r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{1,2},?\s+\d{4})\b",
                re.IGNORECASE,
            )
            date_match = date_pattern.search(title)
            if date_match:
                date_hint = date_match.group(0)

            results.append(
                {
                    "title": title,
                    "link": link,
                    "date_hint": date_hint,
                }
            )

        return results

    # ── Step 3: Try all stored selectors ──────────────────────────────────────
    @staticmethod
    def try_selectors(html: str, selectors: list) -> tuple:
        """
        Iterates through all selector configs. Returns (results, winning_selector)
        where results is a non-empty list and winning_selector is the css string
        that worked. Returns ([], None) if nothing found.
        """
        for sel in selectors:
            try:
                results = RealScraperEngine._extract_with_selector(html, sel)
                if results:
                    print(
                        f"  [Selector HIT] css='{sel['css']}' → {len(results)} items found"
                    )
                    return results, sel["css"]
            except Exception as e:
                print(f"  [Selector ERR] css='{sel['css']}': {e}")
                continue

        return [], None

    @staticmethod
    def llm_recover_selectors(html: str, org_name: str, ai_provider: str, api_key: str, ollama_host: str, ollama_model: str) -> Optional[list]:
        """
        Sends a truncated version of the page HTML to the selected AI provider and asks it to
        identify CSS selectors for the notification/notice list.

        Returns a list of selector dicts (same format as DEFAULT_SELECTORS),
        or None if the LLM could not find any.
        """
        # Truncate HTML to keep token costs reasonable
        char_limit = int(get_setting("llm_html_char_limit", "18000"))
        truncated_html = html[:char_limit]

        prompt = f"""You are an expert web scraper analyzing the HTML of a college/university website.

Organization: {org_name}

I need to find where the "Notifications", "Notices", "Announcements", or "Latest News" section is in the HTML below. These are official notifications for students — things like admission dates, exam schedules, result announcements, fee circulars, etc.

Your task:
1. Analyze the HTML structure.
2. Find CSS selectors that capture individual notification/notice items (each item should contain a title and ideally a link).
3. Return ONLY a valid JSON object (no markdown, no explanation) with this structure:

{{
  "found": true,
  "selectors": [
    {{
      "css": "<CSS selector for each notice item>",
      "title_attr": "text",
      "link_tag": "a",
      "context": "<brief human description of what this targets>"
    }}
  ]
}}

If you absolutely cannot find any notification section, return:
{{
  "found": false,
  "selectors": [],
  "reason": "<explain why>"
}}

HTML (may be truncated):
{truncated_html}
"""

        if ai_provider == "gemini" and api_key:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.5-flash:generateContent?key={api_key}"
            )
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    text_response = (
                        res_data["candidates"][0]["content"]["parts"][0]["text"]
                    ).strip()
            except Exception as e:
                print(f"  [LLM] Gemini request failed: {e}")
                return None
                
        elif ai_provider == "ollama" and ollama_host and ollama_model:
            url = f"{ollama_host.rstrip('/')}/api/generate"
            payload = {
                "model": ollama_model,
                "prompt": prompt,
                "stream": False,
                "format": "json"
            }
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=120) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    text_response = res_data.get("response", "").strip()
            except Exception as e:
                print(f"  [LLM] Ollama request failed: {e}")
                return None
        else:
            print(f"  [LLM] Cannot run recovery — valid provider credentials not found.")
            return None

        # Process the common text_response
        try:
            # Strip markdown code fences if present
            if text_response.startswith("```"):
                text_response = re.sub(r"^```(?:json)?\s*", "", text_response)
                text_response = re.sub(r"\s*```$", "", text_response).strip()

            parsed = json.loads(text_response)

            if not parsed.get("found", False):
                reason = parsed.get("reason", "No reason given")
                print(f"  [LLM] Could not find notifications: {reason}")
                return None

            selectors = parsed.get("selectors", [])
            if not selectors:
                return None

            print(f"  [LLM] Recovered {len(selectors)} selector(s) for {org_name}")
            return selectors
        except json.JSONDecodeError as e:
            print(f"  [LLM] Failed to parse JSON response: {e}\nResponse was: {text_response[:100]}...")
            return None
        except Exception as e:
            print(f"  [LLM] Unexpected error during JSON parsing: {e}")
            return None

    # ── Main entry: run_scrape ─────────────────────────────────────────────────
    @staticmethod
    def run_scrape(org_id: int, api_key: Optional[str] = None, ai_provider: Optional[str] = None, ollama_host: Optional[str] = None, ollama_model: Optional[str] = None) -> list:
        """
        Orchestrates the full scraping pipeline for one organization.

        Returns:
            list of notification dicts ready for the Loader:
            [{title, body, category, source_url, organization_id}]

        Raises:
            FetchError       — website unreachable
            SelectorLostError — website reachable but no notifications found
                                even after LLM recovery attempt
        """
        org = Organization.query.get(org_id)
        if not org:
            raise ValueError(f"Organization ID {org_id} not found")

        website = org.website
        if not website:
            raise FetchError(f"Organization '{org.name}' has no website URL configured")

        print(f"\n[Scraper] Starting real scrape for: {org.name} → {website}")

        # ── 1. Fetch HTML ──────────────────────────────────────────────────────
        html = RealScraperEngine.fetch_html(website)
        print(f"  [Fetch] OK — {len(html):,} chars received")

        # ── 2. Load or create CollegeScrapeConfig ──────────────────────────────
        config = CollegeScrapeConfig.query.filter_by(organization_id=org_id).first()
        if not config:
            config = CollegeScrapeConfig(
                organization_id=org_id,
                notification_selectors=json.dumps(get_default_selectors()),
                selector_health="ok",
                admin_alerted=False,
            )
            db.session.add(config)
            db.session.flush()
            print(
                f"  [Config] Created new scrape config with {len(get_default_selectors())} default selectors"
            )
        else:
            print(
                f"  [Config] Loaded existing scrape config (health: {config.selector_health})"
            )

        # Deserialize stored selectors
        try:
            stored_selectors = json.loads(config.notification_selectors or "[]")
        except (json.JSONDecodeError, TypeError):
            stored_selectors = get_default_selectors()

        if not stored_selectors:
            stored_selectors = get_default_selectors()

        # ── 3. Try stored selectors ────────────────────────────────────────────
        results, winning_css = RealScraperEngine.try_selectors(html, stored_selectors)

        if results:
            # Update config health and last successful selector
            config.selector_health = "ok"
            config.last_successful_selector = winning_css
            config.last_scraped_at = datetime.utcnow()
            config.admin_alerted = False  # Reset alert flag on success
            db.session.commit()

            print(
                f"  [Scraper] ✓ Found {len(results)} notifications via stored selectors"
            )
            return RealScraperEngine._format_results(results, org_id, website)

        # ── 4. Selectors failed → try LLM recovery ────────────────────────────
        print(f"  [Scraper] Stored selectors returned 0 results for {org.name}")

        # Fallback provider logic
        if ai_provider is None:
            ai_provider = "gemini" if api_key else "none"

        can_recover = (ai_provider == "gemini" and api_key) or (ai_provider == "ollama" and ollama_host and ollama_model)

        if can_recover:
            print(f"  [LLM] Attempting selector recovery via {ai_provider.upper()}...")
            new_selectors = RealScraperEngine.llm_recover_selectors(
                html, org.name, ai_provider, api_key, ollama_host, ollama_model
            )

            if new_selectors:
                # Try the LLM-recovered selectors
                results, winning_css = RealScraperEngine.try_selectors(
                    html, new_selectors
                )

                if results:
                    # Save the new selectors to DB
                    config.notification_selectors = json.dumps(new_selectors)
                    config.last_successful_selector = winning_css
                    config.selector_health = "degraded"  # Recovered, but note it
                    config.last_scraped_at = datetime.utcnow()
                    config.llm_recovered_at = datetime.utcnow()
                    config.admin_alerted = False
                    db.session.commit()

                    print(
                        f"  [LLM] ✓ Recovery successful! {len(results)} notifications found. "
                        f"New selectors saved to DB."
                    )
                    return RealScraperEngine._format_results(results, org_id, website)
                else:
                    print(
                        f"  [LLM] Recovery selectors also returned 0 results for {org.name}"
                    )
            else:
                print(f"  [LLM] LLM could not identify any notification selectors")
        else:
            print(
                f"  [Scraper] No AI provider configured — skipping LLM recovery. "
                f"Set AI Provider in Settings to enable adaptive recovery."
            )

        # ── 5. Nothing found → mark as lost, raise ────────────────────────────
        config.selector_health = "lost"
        config.last_scraped_at = datetime.utcnow()

        alert_needed = not config.admin_alerted  # Only alert once per lost state
        if alert_needed:
            config.admin_alerted = True

        db.session.commit()

        raise SelectorLostError(
            f"No notifications found on '{org.name}' ({website}). "
            f"Stored selectors and LLM recovery both failed. "
            f"Admin alert required: {alert_needed}"
        )

    # ── Helper: normalize results ──────────────────────────────────────────────
    @staticmethod
    def _format_results(raw_results: list, org_id: int, base_url: str) -> list:
        """
        Converts raw scraped items into the standard notification dict format
        expected by the Loader Worker.
        """
        formatted = []
        seen_titles = set()

        for item in raw_results:
            title = item.get("title", "").strip()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)

            # Resolve relative URLs
            link = item.get("link") or ""
            if link and not link.startswith(("http://", "https://")):
                # Join relative link with base URL
                base = base_url.rstrip("/")
                if not base.startswith(("http://", "https://")):
                    base = "https://" + base
                link = base + "/" + link.lstrip("/")

            source_url = link or base_url

            # Infer category from title keywords
            category = _infer_category(title)

            formatted.append(
                {
                    "title": title,
                    "body": title,  # Body will be enriched by AI engine later
                    "category": category,
                    "source_url": source_url,
                    "organization_id": org_id,
                    "date_hint": item.get("date_hint"),
                }
            )

        return formatted


# ─── Category inference from title text ──────────────────────────────────────
def _infer_category(title: str) -> str:
    """
    Quick keyword-based category assignment from a notification title.
    Falls back to 'other'.
    Order matters: more specific checks come before generic ones.
    """
    t = title.lower()
    # Check scholarship first — it often contains "application" too
    if any(
        k in t
        for k in [
            "scholarship",
            "fellowship",
            "fellowships",
            "stipend",
            "financial aid",
        ]
    ):
        return "scholarship"
    if any(
        k in t
        for k in [
            "result",
            "merit list",
            "merit-list",
            "rank list",
            "declared",
            "marks",
        ]
    ):
        return "result"
    if any(
        k in t
        for k in ["exam", "examination", "test", "date sheet", "timetable", "schedule"]
    ):
        return "exam"
    if any(
        k in t
        for k in [
            "admission",
            "admissions",
            "apply",
            "application",
            "enroll",
            "registration",
        ]
    ):
        return "admission"
    if any(
        k in t
        for k in [
            "fee",
            "fees",
            "circular",
            "notice",
            "policy",
            "guideline",
            "norms",
            "regulation",
        ]
    ):
        return "policy"
    return "other"


# ─────────────────────────────────────────────────────────────────────────────
#  Legacy Simulation Engine (kept for fallback / orgs with no website)
# ─────────────────────────────────────────────────────────────────────────────
class ScraperEngine:
    """
    Original simulation-based scraper. Used as fallback when:
      - org.website is None/empty
      - HTTP fetch fails (FetchError)
      - SCRAPING_AVAILABLE is False (missing dependencies)

    All original logic is preserved here under simulate_scrape_legacy().
    The public API is simulate_scrape() which delegates to legacy.
    """

    @staticmethod
    def simulate_scrape_legacy(org_id):
        """
        Simulates crawling the website of a registered organization.
        Generates realistic notification announcements depending on the category.
        Preserved from original scraper.py.
        """
        org = Organization.query.get(org_id)
        if not org:
            return None

        print(f"[Legacy Scraper] Simulating crawl for: {org.name} ({org.category})")

        current_year = datetime.now().year

        college_templates = [
            {
                "title": "{org_name} B.Tech & PG Admission {year} Started",
                "body": "Applications are invited for admission to B.Tech, M.Tech, and MBA programs at {org_name} for the academic year {year}. Eligible candidates can register online. Registration starts on June 15, {year} and the last date to submit applications is July 30, {year}. The entrance exam will be held on August 10, {year}. Fee structure: Tuition fee is Rs. 1,20,000 per semester. Scholarships are available for top 10% students based on merit. Total seats: 640.",
                "category": "admission",
                "source_url": "https://{website}/admissions-{year}",
            },
            {
                "title": "{org_name} Announces Merit List for Undergraduate Courses {year}",
                "body": "The first merit list for UG admissions {year} has been released by {org_name}. Candidates who applied can check their status on the official portal. Selected candidates must pay the admission fee and verify documents by July 5, {year} to secure their seats. Merit list release date: June 25, {year}. Counselling sessions will begin from July 10, {year}.",
                "category": "result",
                "source_url": "https://{website}/merit-list",
            },
            {
                "title": "{org_name} Revised Fee Structure and Seat Matrix for {year}-27",
                "body": "The Board of Governors at {org_name} has updated the fee structures and seat matrix for all engineering and science programs. B.Tech tuition fee is revised to Rs. 1,45,000 per semester. New seats have been added to Artificial Intelligence and Data Science courses. Eligibility criteria: Candidate must have scored at least 75% in Class 12 boards.",
                "category": "policy",
                "source_url": "https://{website}/circulars/fees-{year}",
            },
            {
                "title": "{org_name} Placement Report {year}: Average CTC Touches Rs. 18.2 LPA",
                "body": "{org_name} has released its official placement report for the graduating batch of {year}. Over 95% of students got placed with top companies. The highest package offered was Rs. 48 LPA, and the average CTC stood at Rs. 18.2 LPA. Top recruiters included Google, Microsoft, Amazon, and Tata Motors.",
                "category": "other",
                "source_url": "https://{website}/placements/report-{year}",
            },
            {
                "title": "{org_name} Merit-Cum-Means Scholarship Schemes {year}",
                "body": "Applications are open for the Merit-Cum-Means Scholarship at {org_name} for the current academic session. Students with family income less than 5 LPA and GPA above 8.0 are eligible. Scholarship amount covers up to 100% tuition waiver. Registration last date is October 15, {year}.",
                "category": "scholarship",
                "source_url": "https://{website}/scholarships",
            },
        ]

        board_templates = [
            {
                "title": "{org_name} Class 10 & 12 Date Sheet for {year} Board Exams",
                "body": "The date sheet for Class 10 and Class 12 board examinations {year} has been officially published by {org_name}. The examinations will commence on March 1, {year} and end on April 4, {year}. Practical exams will be conducted in January. Admit cards will be available for download from school portals starting February 10, {year}.",
                "category": "exam",
                "source_url": "https://{website}/date-sheet-{year}",
            },
            {
                "title": "{org_name} Class 12 Board Revaluation Results Published",
                "body": "The results for the Class 12 Board exam revaluation and verification have been declared today. Students who applied for re-checking of their answer sheets can view their updated marks on the official results website. Marksheets can be downloaded via DigiLocker. Last date to apply for supplementary exams is June 30, {year}.",
                "category": "result",
                "source_url": "https://{website}/results/reval",
            },
            {
                "title": "{org_name} Academic Calendar and Registration Schedule for {year}-27",
                "body": "{org_name} has announced the academic schedule and student registration dates for schools. Registrations for Class 9 and Class 11 students must be completed online by September 30, {year}. Schools must submit candidate lists with registration fees. Supplementary exams will take place in July.",
                "category": "policy",
                "source_url": "https://{website}/circulars/academic-calendar",
            },
        ]

        regulator_templates = [
            {
                "title": "{org_name} Directives on Minimum Standards for Higher Education",
                "body": "A new circular has been issued by {org_name} regarding minimum qualifications for teachers and academic standards in colleges. All affiliated institutions must implement the credit framework under the National Education Policy. Accreditation by NAAC with at least a 'B' grade is now mandatory for college ranking updates.",
                "category": "policy",
                "source_url": "https://{website}/circulars/academic-standards",
            },
            {
                "title": "{org_name} Approvals Update: 120 New Technical Institutions Approved",
                "body": "{org_name} has released the official approval list for technical colleges and universities for the academic year {year}-27. The council has granted approvals for extension of courses in existing colleges and approved 120 new institutions across India.",
                "category": "policy",
                "source_url": "https://{website}/approvals-{year}",
            },
            {
                "title": "{org_name} National Scholarship Portal (NSP) Applications Extension",
                "body": "The last date to submit online applications for various Central Sector Scholarship schemes on the National Scholarship Portal has been extended. The new deadline for submission is December 31, {year}. Eligible college and university students can apply through the official NSP portal.",
                "category": "scholarship",
                "source_url": "https://{website}/nsp-scholarship",
            },
        ]

        if org.category == "college":
            templates = college_templates
        elif org.category == "board":
            templates = board_templates
        else:
            templates = regulator_templates

        template = random.choice(templates)

        website = org.website or f"{org.aishe_code.lower().replace('-', '')}.edu.in"
        if not (website.startswith("http://") or website.startswith("https://")):
            website_url = website
        else:
            website_url = website.split("//")[-1]

        title = template["title"].format(org_name=org.name, year=current_year)
        body = template["body"].format(org_name=org.name, year=current_year)
        source_url = template["source_url"].format(
            website=website_url, year=current_year
        )

        return {
            "title": title,
            "body": body,
            "category": template["category"],
            "source_url": source_url,
            "organization_id": org.id,
        }

    @staticmethod
    def simulate_scrape(org_id):
        """Delegates to the legacy simulator. Kept for backward compatibility."""
        return ScraperEngine.simulate_scrape_legacy(org_id)

    @staticmethod
    def detect_duplicate(new_title, organization_id):
        """
        Runs duplicate detection. Compares the new notification title against
        other recent notifications from the same or related organizations.
        Optimized with word token intersection filtering before sequence match.
        Returns (is_duplicate, duplicate_of_id)
        """
        new_words = set(new_title.lower().split())
        if not new_words:
            return False, None

        # Fetch active notifications from the same organization within the last 30 days
        recent_notifs = (
            Notification.query.filter(
                Notification.organization_id == organization_id,
                ~Notification.is_duplicate,
            )
            .order_by(Notification.created_at.desc())
            .limit(10)
            .all()
        )

        for notif in recent_notifs:
            notif_words = set(notif.title.lower().split())
            if not notif_words:
                continue
            # Token filter: skip SequenceMatcher if token overlap is too low
            shared = len(new_words.intersection(notif_words))
            if shared / max(len(new_words), len(notif_words)) < 0.4:
                continue

            similarity = difflib.SequenceMatcher(
                None, new_title.lower(), notif.title.lower()
            ).ratio()
            if similarity > 0.85:
                print(
                    f"Duplicate detected: '{new_title}' is {similarity*100:.1f}% similar to '{notif.title}' (ID {notif.id})"
                )
                return True, notif.id

        # Also check cross-organization duplicates
        cross_notifs = (
            Notification.query.filter(~Notification.is_duplicate)
            .order_by(Notification.created_at.desc())
            .limit(20)
            .all()
        )

        for notif in cross_notifs:
            notif_words = set(notif.title.lower().split())
            if not notif_words:
                continue
            shared = len(new_words.intersection(notif_words))
            if shared / max(len(new_words), len(notif_words)) < 0.4:
                continue

            similarity = difflib.SequenceMatcher(
                None, new_title.lower(), notif.title.lower()
            ).ratio()
            if similarity > 0.92:
                print(
                    f"Cross-org duplicate detected: '{new_title}' is {similarity*100:.1f}% similar to '{notif.title}' (ID {notif.id})"
                )
                return True, notif.id

        return False, None

    @staticmethod
    def run_crawling_cycle(org_id, task_id=None):
        """
        Legacy crawling cycle using simulation.
        Kept for backward compatibility; the workers now call run_scrape() directly.
        """
        scraped_data = ScraperEngine.simulate_scrape(org_id)
        if not scraped_data:
            return None

        existing = Notification.query.filter_by(
            organization_id=org_id, title=scraped_data["title"]
        ).first()

        if existing:
            log = CrawlerLog(
                organization_id=org_id,
                status="success",
                detected_changes=False,
                task_id=task_id,
            )
            db.session.add(log)
            db.session.commit()
            print("Crawl complete: Notice already exists in database. No changes.")
            return existing, False

        is_dup, dup_id = ScraperEngine.detect_duplicate(scraped_data["title"], org_id)

        new_notif = Notification(
            organization_id=org_id,
            title=scraped_data["title"],
            body=scraped_data["body"],
            category=scraped_data["category"],
            source_url=scraped_data["source_url"],
            is_duplicate=is_dup,
            duplicate_of_id=dup_id,
            status="Active",
            task_id=task_id,
        )

        db.session.add(new_notif)

        log = CrawlerLog(
            organization_id=org_id,
            status="success",
            detected_changes=True,
            task_id=task_id,
        )
        db.session.add(log)
        db.session.commit()

        print(
            f"Crawl complete: New notification saved (ID: {new_notif.id}, Duplicate: {is_dup})"
        )
        return new_notif, True
