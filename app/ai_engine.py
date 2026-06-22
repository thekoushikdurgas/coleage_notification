import os
import json
import urllib.request
import urllib.error
import re
from datetime import datetime
from app.database import db, Notification, GeneratedContent


class AIEngine:
    @staticmethod
    def extract_dates_and_details(notif_id):
        """
        Simulates AI parsing of raw text to extract key admission dates and criteria.
        Updates the Notification record with extracted details.
        """
        notif = Notification.query.get(notif_id)
        if not notif:
            return

        print(f"Running AI Extraction for notification ID {notif.id}...")

        # Default extraction based on templates
        current_year = datetime.now().year

        # Simple regex/pattern matching to find values in the body text
        body = notif.body

        # Simulating AI Date extraction using text parsing
        notif.application_start_date = f"15 June {current_year}"
        notif.application_end_date = f"30 July {current_year}"

        if "exam will be held on" in body:
            match = re.search(r"held on ([A-Za-z]+ \d+)", body)
            notif.exam_date = (
                f"{match.group(1)} {current_year}"
                if match
                else f"10 August {current_year}"
            )
        elif "exams will commence on" in body:
            match = re.search(r"commence on ([A-Za-z]+ \d+)", body)
            notif.exam_date = (
                f"{match.group(1)} {current_year}"
                if match
                else f"1 March {current_year}"
            )

        if "counselling" in body.lower():
            notif.counselling_date = f"10 July {current_year}"

        if "merit list" in body.lower():
            notif.merit_list_date = f"25 June {current_year}"

        # Parse fees, scholarship, seat matrix, eligibility
        if "fee" in body.lower():
            match = re.search(r"fee is (Rs\.\s*[\d,]+)", body)
            notif.fee_structure = (
                match.group(1) if match else "Rs. 1,20,000 per semester"
            )

        if "scholarship" in body.lower():
            notif.scholarship_details = "Merit-Cum-Means up to 100% tuition waiver"

        if "seat" in body.lower() or "seats" in body.lower():
            match = re.search(r"seats:\s*(\d+)", body)
            notif.seat_matrix = f"{match.group(1)} seats" if match else "640 seats"

        if "eligibility" in body.lower():
            match = re.search(r"criteria:\s*([^.]+)", body)
            notif.eligibility = (
                match.group(1).strip()
                if match
                else "Passed Class 12 with minimum 75% marks"
            )
        else:
            notif.eligibility = (
                "Undergraduate: 10+2 passing; Post-graduate: Relevant Bachelor's Degree"
            )

        db.session.commit()
        print(f"AI Extraction complete for ID {notif.id}.")

    @staticmethod
    def generate_content(notif_id, api_key=None):
        """
        Generates SEO articles, meta tags, social media captions, and push templates.
        Integrates with Gemini API if api_key is provided; falls back to programmatic templates.
        """
        notif = Notification.query.get(notif_id)
        if not notif:
            return None

        org = notif.organization
        print(f"Running AI Content Generation for: {notif.title}")

        # Check if we already have generated content for this notification
        existing = GeneratedContent.query.filter_by(notification_id=notif_id).first()
        if existing:
            return existing

        # Generate a slug
        slug = re.sub(r"[^a-z0-9]+", "-", notif.title.lower()).strip("-")
        # Ensure slug uniqueness by appending id
        slug = f"{slug}-{notif.id}"

        # If API key is available, call Gemini API
        if api_key:
            try:
                content = AIEngine._call_gemini_api(
                    notif.title, notif.body, org.name, api_key
                )
                if content:
                    gen_content = GeneratedContent(
                        notification_id=notif.id,
                        article=content.get("article"),
                        meta_title=content.get("meta_title"),
                        meta_description=content.get("meta_description"),
                        seo_url=slug,
                        social_caption=content.get("social_caption"),
                        whatsapp_message=content.get("whatsapp_message"),
                        telegram_message=content.get("telegram_message"),
                        push_notification=content.get("push_notification"),
                    )
                    db.session.add(gen_content)
                    db.session.commit()
                    return gen_content
            except Exception as e:
                print(
                    f"Gemini API call failed, falling back to programmatic template: {e}"
                )

        # Fallback Programmatic Generation
        article_body = f"""
## Introduction
Official updates have been released regarding **{notif.title}**. {org.name} has published this circular to announce key guidelines, timelines, and structures for candidates. This article provides a comprehensive breakdown of the application process, critical dates, eligibility criteria, and fee structures.

## Complete Overview
The recent update from {org.name} details the official procedures for the upcoming academic session. Candidates are advised to review the details below carefully and visit the official website at `{org.website or 'formsadda.com'}` for registration links and direct forms.

### Important Dates to Remember
- **Online Application Begins:** {notif.application_start_date or 'TBA'}
- **Last Date for Form Submission:** {notif.application_end_date or 'TBA'}
- **Examination Date:** {notif.exam_date or 'TBA'}
- **Merit List / Results Release:** {notif.merit_list_date or 'TBA'}
- **Counselling / Document Verification:** {notif.counselling_date or 'TBA'}

### Eligibility Criteria & Requirements
To apply for the programs, candidates must fulfill the following:
- **Academic Qualifications:** {notif.eligibility or 'Candidate must satisfy the standard criteria.'}
- **Required Documents:** Class 10/12 Marksheets, Category Certificate (if applicable), Identification Proof (Aadhaar/PAN), and Passport-size photos.

### Fee Structure and Seat Allocation
- **Estimated Tuition Fees:** {notif.fee_structure or 'Refer to prospectus.'}
- **Scholarship Opportunities:** {notif.scholarship_details or 'Merit and need-based scholarships are available.'}
- **Seat Matrix:** {notif.seat_matrix or 'Refer to institute guidelines.'}

## Step-by-Step Application Process
1. Visit the official portal of {org.name} at `{org.website or 'formsadda.com'}`.
2. Locate the link for "Admissions / Notifications {datetime.now().year}" and click on it.
3. Register using your email address, mobile number, and personal details.
4. Log in with your new credentials and fill out the detailed application form.
5. Upload scanned copies of the required documents in the prescribed format.
6. Pay the registration fees online using Net Banking, UPI, or Credit/Debit Card.
7. Submit the application and print a copy of the confirmation page for future reference.

For more real-time education updates and exam analysis, stay tuned to FormsADDA.
"""

        meta_title = f"{notif.title} - Eligibility, Apply Online & Dates | FormsADDA"
        meta_desc = f"Looking for information on {notif.title}? Get the complete details regarding eligibility, registration deadlines, exam dates, fee structures, and application links."

        social_caption = f"🚀 Big Update! {notif.title} is now active. Check eligibility criteria, registration deadlines, and how to apply. Full article on FormsADDA. #EducationNews #{org.name.replace(' ', '').replace('-', '').replace(',', '')}"

        whatsapp_msg = f"*📢 FormsADDA Admission Alert*\n\n*{notif.title}*\n\n🗓️ Last Date: {notif.application_end_date or 'TBA'}\n📝 Exam Date: {notif.exam_date or 'TBA'}\n\n👉 Click here to check eligibility, fee structure & apply online:\nhttps://formsadda.com/notifications/{slug}"

        telegram_msg = f"📢 *FormsADDA Education Update*\n\n🚨 *{notif.title}*\n\n📌 *Key Highlights:*\n• Start Date: {notif.application_start_date or 'TBA'}\n• Last Date: {notif.application_end_date or 'TBA'}\n• Exam Date: {notif.exam_date or 'TBA'}\n\n🔗 Read the full post for direct links & step-by-step apply guide:\nhttps://formsadda.com/notifications/{slug}"

        push_notification = (
            f"{notif.title} is started! Check dates, fees, and apply direct link."
        )

        gen_content = GeneratedContent(
            notification_id=notif.id,
            article=article_body.strip(),
            meta_title=meta_title,
            meta_description=meta_desc,
            seo_url=slug,
            social_caption=social_caption,
            whatsapp_message=whatsapp_msg,
            telegram_message=telegram_msg,
            push_notification=push_notification,
        )

        db.session.add(gen_content)
        db.session.commit()

        print(f"AI Content generated successfully for notification ID {notif.id}.")
        return gen_content

    @staticmethod
    def _call_gemini_api(title, body, org_name, api_key):
        """
        Invokes Google Gemini API to generate structured content in JSON.
        """
        # Formulate instructions
        prompt = f"""
You are an expert education content writer and SEO manager for FormsADDA.
Generate high-quality structured content based on the following education notification.

Organization: {org_name}
Title: {title}
Original Details: {body}

Provide a JSON object containing these keys:
1. 'article': A comprehensive 500+ word markdown article describing the announcement, including sections for Introduction, Key Dates, Eligibility, Fees & Seat Matrix, and Application Process.
2. 'meta_title': A compelling SEO title less than 60 characters.
3. 'meta_description': A brief search engine snippet less than 160 characters.
4. 'social_caption': A engaging caption for Instagram/Twitter with appropriate emojis and hashtags.
5. 'whatsapp_message': A short messaging alert utilizing bold formatting.
6. 'telegram_message': A structured announcement using bullet points.
7. 'push_notification': A single sentence alert (less than 80 chars) for push notifications.

Your output must be ONLY the JSON object, with no markdown code blocks (e.g. do not wrap in ```json).
"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                text_response = res_data["candidates"][0]["content"]["parts"][0]["text"]
                # Clean up any potential markdown wraps
                text_response = text_response.strip()
                if text_response.startswith("```json"):
                    text_response = text_response[7:]
                if text_response.endswith("```"):
                    text_response = text_response[:-3]
                text_response = text_response.strip()

                return json.loads(text_response)
        except urllib.error.URLError as ue:
            raise Exception(f"Network error calling Gemini API: {ue}")
        except Exception as e:
            raise Exception(f"Failed to parse Gemini response: {e}")
