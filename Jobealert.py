import os
import re
import smtplib
import requests
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
JSEARCH_API_KEY    = os.environ.get("JSEARCH_API_KEY", "01e85d66d6mshb3ab903659296ccp1bfaf6jsn2d5a17f3e21f")
GMAIL_SENDER       = "megakowshik11111@gmail.com"
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "excq whwj vggn wozi")
RECIPIENT_EMAIL    = "megakowshik11111@gmail.com"
NAUKRI_API_KEY     = os.environ.get("NAUKRI_API_KEY", "")

# ─────────────────────────────────────────────
# RATE-LIMIT SAFE JSEARCH
# Free tier = ~10 requests/minute, 500/month
# We use only 6 broad combined queries instead of 50+
# ─────────────────────────────────────────────

# Broad combined queries — JSearch returns results across all India cities in one call
JSEARCH_QUERIES = [
    "Full Stack Developer React Java India",
    "Frontend Developer React India",
    "Backend Developer Java Python India",
    "AWS Cloud Engineer Developer India",
    "Software Engineer React AWS India",
    "Node.js Java Developer India",
]

JSEARCH_DELAY   = 2.5   # seconds between requests (safe for free tier)
MAX_RESULTS     = 10    # per query (JSearch supports up to 10 per page)


def fetch_jsearch(query: str, retries: int = 3) -> list[dict]:
    url     = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key":  JSEARCH_API_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }
    params  = {
        "query":            query,
        "page":             "1",
        "num_pages":        "1",
        "date_posted":      "3days",      # last 3 days — avoids empty results + today-only misses
        "employment_types": "FULLTIME",
        "results_wanted":   str(MAX_RESULTS),
    }
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=20)
            if resp.status_code == 429:
                wait = 12 * (attempt + 1)
                print(f"    ⚠ Rate limited — waiting {wait}s then retrying...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            jobs = resp.json().get("data", [])
            for job in jobs:
                job["_source_label"] = _detect_source(job)
            return jobs[:MAX_RESULTS]
        except Exception as e:
            print(f"    ⚠ JSearch error on attempt {attempt+1}: {e}")
            time.sleep(5)
    return []


def _detect_source(job: dict) -> str:
    apply_url = (job.get("job_apply_link") or "").lower()
    publisher = (job.get("job_publisher") or "").lower()
    if "linkedin"    in apply_url or "linkedin"    in publisher: return "LinkedIn"
    if "indeed"      in apply_url or "indeed"      in publisher: return "Indeed"
    if "naukri"      in apply_url or "naukri"      in publisher: return "Naukri"
    if "glassdoor"   in apply_url or "glassdoor"   in publisher: return "Glassdoor"
    if "lever.co"    in apply_url:                               return "Lever (Direct)"
    if "greenhouse"  in apply_url:                               return "Greenhouse (Direct)"
    if "workday"     in apply_url:                               return "Workday (Direct)"
    if "myworkday"   in apply_url:                               return "Workday (Direct)"
    if "ziprecruiter" in apply_url or "ziprecruiter" in publisher: return "ZipRecruiter"
    if "careers"     in apply_url or "jobs." in apply_url:       return "Company Careers"
    if publisher:                                                 return publisher.title()[:20]
    return "JSearch"


# ─────────────────────────────────────────────
# SOURCE 2 — NAUKRI via RapidAPI
# Free signup: https://rapidapi.com/apidojo/api/naukri-com1
# ─────────────────────────────────────────────
NAUKRI_QUERIES = [
    ("Full Stack Developer", "Hyderabad"),
    ("React Developer",      "Bangalore"),
    ("Java Developer",       "Chennai"),
    ("AWS Engineer",         "Hyderabad"),
]

def fetch_naukri_jobs() -> list[dict]:
    if not NAUKRI_API_KEY:
        return []
    results = []
    url     = "https://naukri-com1.p.rapidapi.com/auto-complete"
    headers = {
        "X-RapidAPI-Key":  NAUKRI_API_KEY,
        "X-RapidAPI-Host": "naukri-com1.p.rapidapi.com",
    }
    for query, loc in NAUKRI_QUERIES:
        try:
            resp = requests.get(url, headers=headers,
                                params={"query": f"{query} {loc}"}, timeout=15)
            resp.raise_for_status()
            raw  = resp.json()
            jobs = raw.get("jobDetails", raw.get("data", []))
            for j in jobs[:5]:
                results.append({
                    "job_id":          str(j.get("jobId", "")),
                    "job_title":       j.get("title", ""),
                    "employer_name":   j.get("companyName", ""),
                    "job_city":        loc,
                    "job_is_remote":   False,
                    "job_description": j.get("jobDescription", ""),
                    "job_apply_link":  f"https://www.naukri.com/{j.get('jobId','')}",
                    "job_min_salary":  None,
                    "job_max_salary":  None,
                    "_source_label":   "Naukri",
                })
            time.sleep(1)
        except Exception as e:
            print(f"    ⚠ Naukri error for '{query}': {e}")
    return results


# ─────────────────────────────────────────────
# SOURCE 3 — REMOTIVE (100% free, no key)
# Real remote tech jobs from remotive.com
# ─────────────────────────────────────────────
REMOTIVE_CATEGORIES = ["software-dev", "backend-dev", "frontend-dev", "devops-sysadmin"]

def fetch_remotive() -> list[dict]:
    results, seen = [], set()
    for cat in REMOTIVE_CATEGORIES:
        try:
            resp = requests.get("https://remotive.com/api/remote-jobs",
                                params={"category": cat, "limit": 15}, timeout=15)
            resp.raise_for_status()
            for j in resp.json().get("jobs", []):
                jid = str(j.get("id", ""))
                if jid in seen:
                    continue
                seen.add(jid)
                # Filter for India-open or worldwide roles
                loc_req = (j.get("candidate_required_location") or "").lower()
                if loc_req and not any(kw in loc_req for kw in
                        ["india", "worldwide", "anywhere", "global", "asia", "apac", ""]):
                    continue
                results.append({
                    "job_id":          jid,
                    "job_title":       j.get("title", ""),
                    "employer_name":   j.get("company_name", ""),
                    "job_city":        j.get("candidate_required_location") or "Remote",
                    "job_is_remote":   True,
                    "job_description": _strip_html(j.get("description", "")),
                    "job_apply_link":  j.get("url", "#"),
                    "job_min_salary":  None,
                    "job_max_salary":  None,
                    "_source_label":   "Remotive",
                })
            time.sleep(0.5)
        except Exception as e:
            print(f"    ⚠ Remotive error for '{cat}': {e}")
    return results


# ─────────────────────────────────────────────
# SOURCE 4 — LINKEDIN (public job search, no login needed)
# Scrapes LinkedIn's guest-accessible job listings
# ─────────────────────────────────────────────
LINKEDIN_SEARCHES = [
    ("full stack developer",  "India"),
    ("react developer",       "Hyderabad, India"),
    ("java developer",        "Bangalore, India"),
    ("aws engineer",          "India"),
    ("backend developer",     "Chennai, India"),
]

def fetch_linkedin_jobs() -> list[dict]:
    """
    Uses LinkedIn's public jobs API (no login, no key required).
    Returns guest-visible job listings.
    """
    results, seen = [], set()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    for keywords, location in LINKEDIN_SEARCHES:
        try:
            url    = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
            params = {
                "keywords": keywords,
                "location": location,
                "f_TPR":    "r86400",   # last 24 hours
                "f_JT":     "F",        # full-time
                "start":    "0",
            }
            resp = requests.get(url, headers=headers, params=params, timeout=20)
            if resp.status_code != 200:
                print(f"    ⚠ LinkedIn returned {resp.status_code} for '{keywords}'")
                time.sleep(3)
                continue

            # Parse job cards from HTML
            html  = resp.text
            # Extract job IDs from data-entity-urn or href
            ids   = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
            if not ids:
                ids = re.findall(r'/jobs/view/(\d+)/', html)

            titles    = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*(.*?)\s*</h3>', html, re.S)
            companies = re.findall(r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>\s*<a[^>]*>\s*(.*?)\s*</a>', html, re.S)
            locations = re.findall(r'<span[^>]*class="[^"]*job-search-card__location[^"]*"[^>]*>\s*(.*?)\s*</span>', html, re.S)

            for i, jid in enumerate(ids[:8]):
                if jid in seen:
                    continue
                seen.add(jid)
                title   = _clean(titles[i])   if i < len(titles)    else keywords.title()
                company = _clean(companies[i]) if i < len(companies) else "—"
                loc     = _clean(locations[i]) if i < len(locations) else location
                results.append({
                    "job_id":          f"li_{jid}",
                    "job_title":       title,
                    "employer_name":   company,
                    "job_city":        loc,
                    "job_state":       "",
                    "job_country":     "IN",
                    "job_is_remote":   "remote" in loc.lower(),
                    "job_description": "",
                    "job_apply_link":  f"https://www.linkedin.com/jobs/view/{jid}/",
                    "job_min_salary":  None,
                    "job_max_salary":  None,
                    "_source_label":   "LinkedIn",
                })
            print(f"    LinkedIn '{keywords}' in {location} → {len(ids[:8])} jobs")
            time.sleep(2)   # Polite delay
        except Exception as e:
            print(f"    ⚠ LinkedIn error for '{keywords}': {e}")
            time.sleep(3)
    return results


# ─────────────────────────────────────────────
# SOURCE 5 — INDEED (public RSS feed, no key)
# ─────────────────────────────────────────────
INDEED_SEARCHES = [
    ("full stack developer", "Hyderabad"),
    ("react developer",      "Bangalore"),
    ("aws developer",        "India"),
    ("java developer",       "Chennai"),
]

def fetch_indeed_jobs() -> list[dict]:
    """Uses Indeed's public RSS feed — no API key needed."""
    results, seen = [], set()
    for query, location in INDEED_SEARCHES:
        try:
            rss_url = (
                f"https://in.indeed.com/rss?q={requests.utils.quote(query)}"
                f"&l={requests.utils.quote(location)}&sort=date&limit=10"
            )
            headers = {"User-Agent": "Mozilla/5.0 (compatible; Feedfetcher-Google)"}
            resp    = requests.get(rss_url, headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"    ⚠ Indeed RSS {resp.status_code} for '{query}'")
                time.sleep(2)
                continue

            xml = resp.text
            # Parse RSS items
            items    = re.findall(r"<item>(.*?)</item>", xml, re.S)
            count    = 0
            for item in items:
                title_m   = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>",   item)
                link_m    = re.search(r"<link>(.*?)</link>",                      item)
                company_m = re.search(r"<source[^>]*>(.*?)</source>",             item)
                desc_m    = re.search(r"<description><!\[CDATA\[(.*?)\]\]></description>", item, re.S)

                title   = _clean(title_m.group(1))   if title_m   else query.title()
                link    = link_m.group(1).strip()     if link_m    else "#"
                company = _clean(company_m.group(1)) if company_m else "—"
                desc    = _strip_html(desc_m.group(1)) if desc_m  else ""

                # Deduplicate by link
                if link in seen:
                    continue
                seen.add(link)
                results.append({
                    "job_id":          f"indeed_{hash(link)}",
                    "job_title":       title,
                    "employer_name":   company,
                    "job_city":        location,
                    "job_state":       "",
                    "job_country":     "IN",
                    "job_is_remote":   False,
                    "job_description": desc,
                    "job_apply_link":  link,
                    "job_min_salary":  None,
                    "job_max_salary":  None,
                    "_source_label":   "Indeed",
                })
                count += 1
            print(f"    Indeed '{query}' in {location} → {count} jobs")
            time.sleep(1.5)
        except Exception as e:
            print(f"    ⚠ Indeed error for '{query}': {e}")
    return results


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", _strip_html(text)).strip()


# ─────────────────────────────────────────────
# AGGREGATE ALL SOURCES
# ─────────────────────────────────────────────
def get_all_jobs() -> list[dict]:
    all_jobs, seen_ids = [], set()

    def add(jobs: list[dict]):
        for job in jobs:
            jid = job.get("job_id", "") or str(id(job))
            if jid not in seen_ids:
                seen_ids.add(jid)
                all_jobs.append(job)

    # 1. LinkedIn (free, no key)
    print("\n  [1/5] LinkedIn (public API)...")
    add(fetch_linkedin_jobs())

    # 2. Indeed RSS (free, no key)
    print("\n  [2/5] Indeed (RSS feed)...")
    add(fetch_indeed_jobs())

    # 3. Remotive (free, no key)
    print("\n  [3/5] Remotive (remote jobs)...")
    add(fetch_remotive())

    # 4. JSearch — only 6 broad calls now, well within free tier
    print(f"\n  [4/5] JSearch ({len(JSEARCH_QUERIES)} smart combined queries)...")
    for q in JSEARCH_QUERIES:
        print(f"    Querying: {q}...")
        add(fetch_jsearch(q))
        time.sleep(JSEARCH_DELAY)

    # 5. Naukri (if key set)
    print("\n  [5/5] Naukri...")
    if NAUKRI_API_KEY:
        add(fetch_naukri_jobs())
    else:
        print("    (Skipped — set NAUKRI_API_KEY to enable)")
        print("    Free key: https://rapidapi.com/apidojo/api/naukri-com1")

    print(f"\n  ✅ Total unique jobs: {len(all_jobs)}")
    return all_jobs


# ─────────────────────────────────────────────
# FORMAT HELPERS
# ─────────────────────────────────────────────
def format_salary(job: dict) -> str:
    min_s    = job.get("job_min_salary")
    max_s    = job.get("job_max_salary")
    currency = job.get("job_salary_currency", "")
    period   = job.get("job_salary_period", "")
    if min_s and max_s:
        if currency == "INR" and period and "YEAR" in period.upper():
            return f"₹{min_s/100000:.0f}–{max_s/100000:.0f} LPA"
        return f"{currency} {int(min_s):,}–{int(max_s):,}"
    return "Not disclosed"


def get_location_badge(job: dict) -> tuple[str, str]:
    if job.get("job_is_remote"):
        return "Remote", "remote"
    city  = (job.get("job_city")  or "").lower()
    loc   = city
    if "bangalore" in loc or "bengaluru" in loc: return "Bangalore", "bangalore"
    if "hyderabad" in loc:                        return "Hyderabad", "hyderabad"
    if "chennai"   in loc:                        return "Chennai",   "chennai"
    if "mysore"    in loc or "mysuru" in loc:     return "Mysore",    "mysore"
    label = (job.get("job_city") or job.get("job_country") or "India")[:20]
    return label, "other"


def truncate(text: str, n: int = 90) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text[:n] + "…" if len(text) > n else text or "—"


# ─────────────────────────────────────────────
# BADGE STYLES
# ─────────────────────────────────────────────
SRC_STYLES = {
    "LinkedIn":             "background:#E8F0FA;color:#0A66C2;",
    "Indeed":               "background:#FDF0E0;color:#D0401B;",
    "Naukri":               "background:#FAEAFF;color:#7B19B0;",
    "Glassdoor":            "background:#E6F9ED;color:#0CAA41;",
    "Remotive":             "background:#EBF5FB;color:#1A6E9F;",
    "Lever (Direct)":       "background:#FFF3E0;color:#E65100;",
    "Greenhouse (Direct)":  "background:#E8F5E9;color:#2E7D32;",
    "Workday (Direct)":     "background:#FCE4EC;color:#880E4F;",
    "ZipRecruiter":         "background:#FFF8E1;color:#827717;",
    "Company Careers":      "background:#F3E5F5;color:#6A1B9A;",
}

LOC_STYLES = {
    "remote":    "background:#E1F5EE;color:#0F6E56;",
    "bangalore": "background:#E6F1FB;color:#185FA5;",
    "hyderabad": "background:#FAEEDA;color:#854F0B;",
    "chennai":   "background:#FBEAF0;color:#993556;",
    "mysore":    "background:#EAF3DE;color:#3B6D11;",
    "other":     "background:#F1EFE8;color:#5F5E5A;",
}


# ─────────────────────────────────────────────
# BUILD HTML EMAIL
# ─────────────────────────────────────────────
def build_html_email(jobs: list[dict]) -> str:
    today = datetime.now().strftime("%d %B %Y")

    src_counts: dict[str, int] = {}
    for j in jobs:
        s = j.get("_source_label", "JSearch")
        src_counts[s] = src_counts.get(s, 0) + 1

    src_summary = " &nbsp;·&nbsp; ".join(
        f'<span style="font-weight:600;">{v}</span> {k}'
        for k, v in sorted(src_counts.items(), key=lambda x: -x[1])
    )

    rows = ""
    if not jobs:
        rows = '<tr><td colspan="7" style="padding:24px;text-align:center;color:#888;">No jobs found today. Check back tomorrow!</td></tr>'
    else:
        for job in jobs:
            company  = (job.get("employer_name") or "Unknown")[:28]
            title    = (job.get("job_title")     or "—")[:35]
            url      = job.get("job_apply_link") or "#"
            desc     = truncate(job.get("job_description") or "", 90)
            salary   = format_salary(job)
            src      = job.get("_source_label", "JSearch")
            loc_txt, loc_key = get_location_badge(job)

            ls  = LOC_STYLES.get(loc_key, LOC_STYLES["other"])
            ss  = SRC_STYLES.get(src, "background:#F1EFE8;color:#5F5E5A;")

            rows += f"""
      <tr style="border-bottom:0.5px solid #eee;">
        <td style="padding:10px 12px;font-weight:500;font-size:13px;color:#111;vertical-align:top;">{company}</td>
        <td style="padding:10px 12px;font-size:13px;color:#111;vertical-align:top;">{title}</td>
        <td style="padding:10px 12px;font-size:12px;color:#444;vertical-align:top;white-space:nowrap;">{salary}</td>
        <td style="padding:10px 12px;vertical-align:top;">
          <span style="display:inline-block;{ls}font-size:11px;padding:3px 8px;border-radius:20px;">{loc_txt}</span>
        </td>
        <td style="padding:10px 12px;vertical-align:top;">
          <span style="display:inline-block;{ss}font-size:11px;padding:3px 8px;border-radius:20px;">{src}</span>
        </td>
        <td style="padding:10px 12px;font-size:12px;color:#555;vertical-align:top;">{desc}</td>
        <td style="padding:10px 12px;vertical-align:top;">
          <a href="{url}" style="display:inline-block;background:#0F6E56;color:#fff;font-size:12px;padding:5px 12px;border-radius:6px;text-decoration:none;">Apply ↗</a>
        </td>
      </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:980px;margin:24px auto;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e0e0e0;">

  <div style="background:#0F6E56;padding:20px 28px;">
    <div style="font-size:18px;font-weight:600;color:#E1F5EE;">📋 Daily Job Digest — {today}</div>
    <div style="font-size:13px;color:#9FE1CB;margin-top:4px;">
      {len(jobs)} job{'s' if len(jobs)!=1 else ''} · LinkedIn · Indeed · Remotive · JSearch · Naukri
    </div>
  </div>

  <div style="background:#FAFFF9;padding:12px 28px;border-bottom:1px solid #e8f5e0;font-size:12px;color:#555;">
    📊 {src_summary}
  </div>

  <div style="padding:20px 28px 8px;">
    <p style="font-size:14px;color:#444;margin:0;">
      Hi Koushik 👋 — fresh jobs across <strong>LinkedIn, Indeed, Remotive, JSearch &amp; Naukri</strong> for
      Full Stack · Frontend · Backend · AWS roles in Hyderabad, Bangalore, Chennai &amp; Remote.
    </p>
  </div>

  <div style="padding:8px 16px 20px;overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;font-family:inherit;">
      <thead>
        <tr style="background:#f8f8f8;border-bottom:1px solid #e0e0e0;">
          <th style="padding:10px 12px;text-align:left;font-size:12px;color:#888;font-weight:500;">Company</th>
          <th style="padding:10px 12px;text-align:left;font-size:12px;color:#888;font-weight:500;">Role</th>
          <th style="padding:10px 12px;text-align:left;font-size:12px;color:#888;font-weight:500;">CTC</th>
          <th style="padding:10px 12px;text-align:left;font-size:12px;color:#888;font-weight:500;">Location</th>
          <th style="padding:10px 12px;text-align:left;font-size:12px;color:#888;font-weight:500;">Source</th>
          <th style="padding:10px 12px;text-align:left;font-size:12px;color:#888;font-weight:500;">About</th>
          <th style="padding:10px 12px;text-align:left;font-size:12px;color:#888;font-weight:500;">Apply</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>

  <div style="background:#f8f8f8;padding:16px 28px;border-top:1px solid #e0e0e0;">
    <p style="font-size:12px;color:#aaa;margin:0;">
      Auto-generated · Sources: LinkedIn (public API) · Indeed (RSS) · Remotive (free) · JSearch (6 calls/day, safe) · Naukri (optional key) · {today}
    </p>
  </div>

</div>
</body>
</html>"""


# ─────────────────────────────────────────────
# SEND EMAIL
# ─────────────────────────────────────────────
def send_email(html_body: str, job_count: int):
    today   = datetime.now().strftime("%d %b %Y")
    subject = f"🔔 {job_count} New Jobs for You — {today}"
    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_SENDER
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText(f"Daily Job Digest — {today}\n{job_count} jobs found.", "plain"))
    msg.attach(MIMEText(html_body, "html"))
    print(f"\n  Sending email to {RECIPIENT_EMAIL}...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_SENDER, RECIPIENT_EMAIL, msg.as_string())
    print(f"  ✅ Email sent! Subject: {subject}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("=" * 55)
    print(f"  Daily Job Alert — {datetime.now().strftime('%d %b %Y %H:%M')}")
    print("=" * 55)
    print("\n  Sources:")
    print("    ✅ LinkedIn    — public job API (no key)")
    print("    ✅ Indeed      — RSS feed (no key)")
    print("    ✅ Remotive    — remote jobs (no key)")
    print(f"   ✅ JSearch    — {len(JSEARCH_QUERIES)} calls only (rate-limit safe)")
    print(f"   {'✅ Naukri' if NAUKRI_API_KEY else '⏭  Naukri (set NAUKRI_API_KEY to enable)'}")

    jobs = get_all_jobs()
    html = build_html_email(jobs)
    send_email(html, len(jobs))

    print("\n  Done ✅")
    print("=" * 55)


if __name__ == "__main__":
    main()
