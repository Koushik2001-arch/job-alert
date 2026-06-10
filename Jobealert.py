
import os
import smtplib
import requests
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIG — edit here or set as env variables
# ─────────────────────────────────────────────
JSEARCH_API_KEY    = os.environ.get("jsearch.p.rapidapi.com", "01e85d66d6mshb3ab903659296ccp1bfaf6jsn2d5a17f3e21f")
GMAIL_SENDER       = "megakowshik11111@gmail.com"
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "excq whwj vggn wozi")
RECIPIENT_EMAIL    = "megakowshik11111@gmail.com"

# Job search config
SEARCH_QUERIES = [
    "Full Stack Developer",
    "Frontend Developer",
    "React Developer",
    "Backend Developer",
    "AWS Developer",
    "AWS Cloud Engineer",
]

LOCATIONS = [
    "Hyderabad India",
    "Bangalore India",
    "Chennai India",
    "Mysore India",
    "Remote India",
]

# Max jobs per query (JSearch free tier: 500 calls/month)
MAX_JOBS_PER_QUERY = 5


# ─────────────────────────────────────────────
# FETCH JOBS FROM JSEARCH
# ─────────────────────────────────────────────
def fetch_jobs(query: str, location: str) -> list[dict]:
    url = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": JSEARCH_API_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
    }
    params = {
        "query": f"{query} in {location}",
        "page": "1",
        "num_pages": "1",
        "date_posted": "today",
        "employment_types": "FULLTIME",
    }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])[:MAX_JOBS_PER_QUERY]
    except Exception as e:
        print(f"  ⚠ Failed to fetch '{query}' in {location}: {e}")
        return []


def get_all_jobs() -> list[dict]:
    all_jobs = []
    seen_ids = set()

    for query in SEARCH_QUERIES:
        for location in LOCATIONS:
            print(f"  Searching: {query} in {location}...")
            jobs = fetch_jobs(query, location)
            for job in jobs:
                job_id = job.get("job_id", "")
                if job_id and job_id not in seen_ids:
                    seen_ids.add(job_id)
                    all_jobs.append(job)

    print(f"\n  Total unique jobs found: {len(all_jobs)}")
    return all_jobs


# ─────────────────────────────────────────────
# FORMAT JOB DATA
# ─────────────────────────────────────────────
def format_salary(job: dict) -> str:
    min_s = job.get("job_min_salary")
    max_s = job.get("job_max_salary")
    currency = job.get("job_salary_currency", "")
    period = job.get("job_salary_period", "")

    if min_s and max_s:
        if currency == "INR":
            # Convert to LPA if annual
            if period and "YEAR" in period.upper():
                return f"₹{min_s/100000:.0f}–{max_s/100000:.0f} LPA"
            return f"₹{int(min_s):,}–{int(max_s):,}"
        return f"{currency} {int(min_s):,}–{int(max_s):,}"
    return "Not disclosed"


def get_location_badge(job: dict) -> tuple[str, str]:
    is_remote = job.get("job_is_remote", False)
    city = job.get("job_city", "") or ""
    state = job.get("job_state", "") or ""
    country = job.get("job_country", "") or ""

    if is_remote:
        return "Remote", "remote"

    location_parts = [p for p in [city, state] if p]
    location_str = ", ".join(location_parts) if location_parts else country

    location_lower = location_str.lower()
    if "bangalore" in location_lower or "bengaluru" in location_lower:
        return "Bangalore", "bangalore"
    elif "hyderabad" in location_lower:
        return "Hyderabad", "hyderabad"
    elif "chennai" in location_lower:
        return "Chennai", "chennai"
    elif "mysore" in location_lower or "mysuru" in location_lower:
        return "Mysore", "mysore"
    elif location_str:
        return location_str[:20], "other"
    return "India", "other"


def truncate(text: str, max_len: int = 80) -> str:
    if not text:
        return "—"
    text = text.strip().replace("\n", " ")
    return text[:max_len] + "…" if len(text) > max_len else text


# ─────────────────────────────────────────────
# BUILD HTML EMAIL
# ─────────────────────────────────────────────
BADGE_STYLES = {
    "remote":    "background:#E1F5EE;color:#0F6E56;",
    "bangalore": "background:#E6F1FB;color:#185FA5;",
    "hyderabad": "background:#FAEEDA;color:#854F0B;",
    "chennai":   "background:#FBEAF0;color:#993556;",
    "mysore":    "background:#EAF3DE;color:#3B6D11;",
    "other":     "background:#F1EFE8;color:#5F5E5A;",
}


def build_html_email(jobs: list[dict]) -> str:
    today = datetime.now().strftime("%d %B %Y")

    rows_html = ""
    if not jobs:
        rows_html = """
        <tr>
          <td colspan="6" style="padding:24px;text-align:center;color:#888;font-size:13px;">
            No new jobs found in the last 24 hours matching your profile. Check back tomorrow!
          </td>
        </tr>"""
    else:
        for job in jobs:
            company   = job.get("employer_name", "Unknown") or "Unknown"
            title     = job.get("job_title", "—") or "—"
            apply_url = job.get("job_apply_link", "#") or "#"
            desc      = truncate(job.get("job_description", ""), 85)
            salary    = format_salary(job)
            loc_text, loc_key = get_location_badge(job)
            badge_style = BADGE_STYLES.get(loc_key, BADGE_STYLES["other"])

            rows_html += f"""
        <tr style="border-bottom:0.5px solid #eee;">
          <td style="padding:10px 12px;font-weight:500;font-size:13px;color:#111;vertical-align:top;">{company[:25]}</td>
          <td style="padding:10px 12px;font-size:13px;color:#111;vertical-align:top;">{title[:30]}</td>
          <td style="padding:10px 12px;font-size:12px;color:#444;vertical-align:top;white-space:nowrap;">{salary}</td>
          <td style="padding:10px 12px;vertical-align:top;">
            <span style="display:inline-block;{badge_style}font-size:11px;padding:3px 8px;border-radius:20px;">{loc_text}</span>
          </td>
          <td style="padding:10px 12px;font-size:12px;color:#555;vertical-align:top;">{desc}</td>
          <td style="padding:10px 12px;vertical-align:top;">
            <a href="{apply_url}" style="display:inline-block;background:#0F6E56;color:#ffffff;font-size:12px;padding:5px 12px;border-radius:6px;text-decoration:none;">Apply ↗</a>
          </td>
        </tr>"""

    job_count = len(jobs)

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">

  <div style="max-width:900px;margin:24px auto;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e0e0e0;">

    <!-- Header -->
    <div style="background:#0F6E56;padding:20px 28px;">
      <div style="font-size:18px;font-weight:600;color:#E1F5EE;">📋 Daily Job Digest — {today}</div>
      <div style="font-size:13px;color:#9FE1CB;margin-top:4px;">
        {job_count} new job{'s' if job_count != 1 else ''} found · Full Stack · Frontend · Backend · AWS · Hyderabad / Bangalore / Chennai / Mysore / Remote
      </div>
    </div>

    <!-- Intro -->
    <div style="padding:20px 28px 8px;">
      <p style="font-size:14px;color:#444;margin:0;">
        Hi Koushik 👋 — here are fresh job postings matching your profile from the last 24 hours.
        Roles filtered for <strong>Full Stack, Frontend, Backend &amp; AWS</strong> positions across your preferred locations.
      </p>
    </div>

    <!-- Job Table -->
    <div style="padding:8px 16px 20px;overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-family:inherit;">
        <thead>
          <tr style="background:#f8f8f8;border-bottom:1px solid #e0e0e0;">
            <th style="padding:10px 12px;text-align:left;font-size:12px;color:#888;font-weight:500;">Company</th>
            <th style="padding:10px 12px;text-align:left;font-size:12px;color:#888;font-weight:500;">Role</th>
            <th style="padding:10px 12px;text-align:left;font-size:12px;color:#888;font-weight:500;">CTC</th>
            <th style="padding:10px 12px;text-align:left;font-size:12px;color:#888;font-weight:500;">Location</th>
            <th style="padding:10px 12px;text-align:left;font-size:12px;color:#888;font-weight:500;">About</th>
            <th style="padding:10px 12px;text-align:left;font-size:12px;color:#888;font-weight:500;">Apply</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </div>

    <!-- Footer -->
    <div style="background:#f8f8f8;padding:16px 28px;border-top:1px solid #e0e0e0;">
      <p style="font-size:12px;color:#aaa;margin:0;">
        This email was auto-generated by your job alert script · Jobs from JSearch (LinkedIn, Indeed, Glassdoor) ·
        Filtered: posted in last 24 hrs · {today}
      </p>
    </div>

  </div>
</body>
</html>"""
    return html


# ─────────────────────────────────────────────
# SEND EMAIL VIA GMAIL SMTP
# ─────────────────────────────────────────────
def send_email(html_body: str, job_count: int):
    today = datetime.now().strftime("%d %b %Y")
    subject = f"🔔 {job_count} New Jobs for You — {today}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_SENDER
    msg["To"]      = RECIPIENT_EMAIL

    # Plain text fallback
    plain = f"Daily Job Digest — {today}\n{job_count} new jobs found.\nOpen this email in an HTML-capable client to view the full table."
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    print(f"\n  Sending email to {RECIPIENT_EMAIL}...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_SENDER, RECIPIENT_EMAIL, msg.as_string())
    print(f"  ✅ Email sent successfully! Subject: {subject}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("=" * 50)
    print(f"  Daily Job Alert — {datetime.now().strftime('%d %b %Y %H:%M')}")
    print("=" * 50)

    

    print("\n  Fetching jobs...")
    jobs = get_all_jobs()

    print("\n  Building email...")
    html = build_html_email(jobs)

    send_email(html, len(jobs))

    print("\n  Done. ✅")
    print("=" * 50)


if __name__ == "__main__":
    main()