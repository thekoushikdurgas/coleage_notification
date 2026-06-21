import random
import difflib
from datetime import datetime
from app.database import db, Organization, Notification, CrawlerLog

class ScraperEngine:
    @staticmethod
    def simulate_scrape(org_id):
        """
        Simulates crawling the website of a registered organization.
        Generates realistic notification announcements depending on the category.
        """
        org = Organization.query.get(org_id)
        if not org:
            return None
            
        print(f"Simulating crawl for: {org.name} ({org.category})")
        
        # Templates for different categories
        current_year = datetime.now().year
        
        college_templates = [
            {
                "title": "{org_name} B.Tech & PG Admission {year} Started",
                "body": "Applications are invited for admission to B.Tech, M.Tech, and MBA programs at {org_name} for the academic year {year}. Eligible candidates can register online. Registration starts on June 15, {year} and the last date to submit applications is July 30, {year}. The entrance exam will be held on August 10, {year}. Fee structure: Tuition fee is Rs. 1,20,000 per semester. Scholarships are available for top 10% students based on merit. Total seats: 640.",
                "category": "admission",
                "source_url": "https://{website}/admissions-{year}"
            },
            {
                "title": "{org_name} Announces Merit List for Undergraduate Courses {year}",
                "body": "The first merit list for UG admissions {year} has been released by {org_name}. Candidates who applied can check their status on the official portal. Selected candidates must pay the admission fee and verify documents by July 5, {year} to secure their seats. Merit list release date: June 25, {year}. Counselling sessions will begin from July 10, {year}.",
                "category": "result",
                "source_url": "https://{website}/merit-list"
            },
            {
                "title": "{org_name} Revised Fee Structure and Seat Matrix for {year}-27",
                "body": "The Board of Governors at {org_name} has updated the fee structures and seat matrix for all engineering and science programs. B.Tech tuition fee is revised to Rs. 1,45,000 per semester. New seats have been added to Artificial Intelligence and Data Science courses. Eligibility criteria: Candidate must have scored at least 75% in Class 12 boards.",
                "category": "policy",
                "source_url": "https://{website}/circulars/fees-{year}"
            },
            {
                "title": "{org_name} Placement Report {year}: Average CTC Touches Rs. 18.2 LPA",
                "body": "{org_name} has released its official placement report for the graduating batch of {year}. Over 95% of students got placed with top companies. The highest package offered was Rs. 48 LPA, and the average CTC stood at Rs. 18.2 LPA. Top recruiters included Google, Microsoft, Amazon, and Tata Motors.",
                "category": "other",
                "source_url": "https://{website}/placements/report-{year}"
            },
            {
                "title": "{org_name} Merit-Cum-Means Scholarship Schemes {year}",
                "body": "Applications are open for the Merit-Cum-Means Scholarship at {org_name} for the current academic session. Students with family income less than 5 LPA and GPA above 8.0 are eligible. Scholarship amount covers up to 100% tuition waiver. Registration last date is October 15, {year}.",
                "category": "scholarship",
                "source_url": "https://{website}/scholarships"
            }
        ]
        
        board_templates = [
            {
                "title": "{org_name} Class 10 & 12 Date Sheet for {year} Board Exams",
                "body": "The date sheet for Class 10 and Class 12 board examinations {year} has been officially published by {org_name}. The examinations will commence on March 1, {year} and end on April 4, {year}. Practical exams will be conducted in January. Admit cards will be available for download from school portals starting February 10, {year}.",
                "category": "exam",
                "source_url": "https://{website}/date-sheet-{year}"
            },
            {
                "title": "{org_name} Class 12 Board Revaluation Results Published",
                "body": "The results for the Class 12 Board exam revaluation and verification have been declared today. Students who applied for re-checking of their answer sheets can view their updated marks on the official results website. Marksheets can be downloaded via DigiLocker. Last date to apply for supplementary exams is June 30, {year}.",
                "category": "result",
                "source_url": "https://{website}/results/reval"
            },
            {
                "title": "{org_name} Academic Calendar and Registration Schedule for {year}-27",
                "body": "{org_name} has announced the academic schedule and student registration dates for schools. Registrations for Class 9 and Class 11 students must be completed online by September 30, {year}. Schools must submit candidate lists with registration fees. Supplementary exams will take place in July.",
                "category": "policy",
                "source_url": "https://{website}/circulars/academic-calendar"
            }
        ]
        
        regulator_templates = [
            {
                "title": "{org_name} Directives on Minimum Standards for Higher Education",
                "body": "A new circular has been issued by {org_name} regarding minimum qualifications for teachers and academic standards in colleges. All affiliated institutions must implement the credit framework under the National Education Policy. Accreditation by NAAC with at least a 'B' grade is now mandatory for college ranking updates.",
                "category": "policy",
                "source_url": "https://{website}/circulars/academic-standards"
            },
            {
                "title": "{org_name} Approvals Update: 120 New Technical Institutions Approved",
                "body": "{org_name} has released the official approval list for technical colleges and universities for the academic year {year}-27. The council has granted approvals for extension of courses in existing colleges and approved 120 new institutions across India.",
                "category": "policy",
                "source_url": "https://{website}/approvals-{year}"
            },
            {
                "title": "{org_name} National Scholarship Portal (NSP) Applications Extension",
                "body": "The last date to submit online applications for various Central Sector Scholarship schemes on the National Scholarship Portal has been extended. The new deadline for submission is December 31, {year}. Eligible college and university students can apply through the official NSP portal.",
                "category": "scholarship",
                "source_url": "https://{website}/nsp-scholarship"
            }
        ]
        
        # Select appropriate templates
        if org.category == 'college':
            templates = college_templates
        elif org.category == 'board':
            templates = board_templates
        else:
            templates = regulator_templates
            
        template = random.choice(templates)
        
        # Clean website URL
        website = org.website or f"{org.aishe_code.lower().replace('-', '')}.edu.in"
        if not (website.startswith('http://') or website.startswith('https://')):
            website_url = website
        else:
            website_url = website.split('//')[-1]
            
        # Format the title and body
        title = template["title"].format(org_name=org.name, year=current_year)
        body = template["body"].format(org_name=org.name, year=current_year)
        source_url = template["source_url"].format(website=website_url, year=current_year)
        
        return {
            "title": title,
            "body": body,
            "category": template["category"],
            "source_url": source_url,
            "organization_id": org.id
        }
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
        recent_notifs = Notification.query.filter(
            Notification.organization_id == organization_id,
            Notification.is_duplicate == False
        ).order_by(Notification.created_at.desc()).limit(10).all()
        
        for notif in recent_notifs:
            notif_words = set(notif.title.lower().split())
            if not notif_words:
                continue
            # Token filter: skip SequenceMatcher if token overlap is too low
            shared = len(new_words.intersection(notif_words))
            if shared / max(len(new_words), len(notif_words)) < 0.4:
                continue

            similarity = difflib.SequenceMatcher(None, new_title.lower(), notif.title.lower()).ratio()
            if similarity > 0.85:
                print(f"Duplicate detected: '{new_title}' is {similarity*100:.1f}% similar to '{notif.title}' (ID {notif.id})")
                return True, notif.id
                
        # Also check cross-organization duplicates (e.g. CBSE and state news reporting the exact same title)
        cross_notifs = Notification.query.filter(
            Notification.is_duplicate == False
        ).order_by(Notification.created_at.desc()).limit(20).all()
        
        for notif in cross_notifs:
            notif_words = set(notif.title.lower().split())
            if not notif_words:
                continue
            shared = len(new_words.intersection(notif_words))
            if shared / max(len(new_words), len(notif_words)) < 0.4:
                continue

            similarity = difflib.SequenceMatcher(None, new_title.lower(), notif.title.lower()).ratio()
            if similarity > 0.92:
                print(f"Cross-org duplicate detected: '{new_title}' is {similarity*100:.1f}% similar to '{notif.title}' (ID {notif.id})")
                return True, notif.id
                
        return False, None

    @staticmethod
    def run_crawling_cycle(org_id, task_id=None):
        """
        Simulates a full crawling cycle for a single organization:
        1. Simulate scrape.
        2. Detect changes (check if identical notice exists).
        3. Check duplicates.
        4. Save to DB (marking duplicate flag).
        5. Log the crawl action.
        """
        scraped_data = ScraperEngine.simulate_scrape(org_id)
        if not scraped_data:
            return None
            
        # Check if this exact title has already been ingested for this org
        existing = Notification.query.filter_by(
            organization_id=org_id,
            title=scraped_data["title"]
        ).first()
        
        if existing:
            # Log successful crawl, but no new changes detected
            log = CrawlerLog(organization_id=org_id, status='success', detected_changes=False, task_id=task_id)
            db.session.add(log)
            db.session.commit()
            print("Crawl complete: Notice already exists in database. No changes.")
            return existing, False # Return existing, is_new=False
            
        # Run duplicate detection
        is_dup, dup_id = ScraperEngine.detect_duplicate(scraped_data["title"], org_id)
        
        # Save new notification
        new_notif = Notification(
            organization_id=org_id,
            title=scraped_data["title"],
            body=scraped_data["body"],
            category=scraped_data["category"],
            source_url=scraped_data["source_url"],
            is_duplicate=is_dup,
            duplicate_of_id=dup_id,
            status='Active',
            task_id=task_id
        )
        
        db.session.add(new_notif)
        
        # Log successful crawl with changes
        log = CrawlerLog(organization_id=org_id, status='success', detected_changes=True, task_id=task_id)
        db.session.add(log)
        db.session.commit()
        
        print(f"Crawl complete: New notification saved (ID: {new_notif.id}, Duplicate: {is_dup})")
        return new_notif, True # Return new notification, is_new=True
