"""
Daily Scanner — runs for all users via GitHub Actions.
Sends personalised alerts with startup/funding highlights.
"""
import os, requests
from http.server import BaseHTTPRequestHandler
from api.jobs import get_all_jobs, matches_user, matches_location, matches_seniority, fmt_date, score

BOT_TOKEN    = os.environ.get("JOB_BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
TG_API       = f"https://api.telegram.org/bot{BOT_TOKEN}"

def db_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

def get_all_users():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?active=eq.true&setup_complete=eq.true&select=*",
        headers=db_headers(), timeout=10)
    return r.json() if r.status_code == 200 else []

def get_sent_ids(chat_id):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/sent_jobs?chat_id=eq.{chat_id}&select=job_id",
        headers=db_headers(), timeout=10)
    return {row["job_id"] for row in r.json()} if r.status_code == 200 else set()

def mark_sent(chat_id, job_ids):
    if not job_ids:
        return
    requests.post(
        f"{SUPABASE_URL}/rest/v1/sent_jobs",
        headers={**db_headers(), "Prefer": "resolution=ignore-duplicates"},
        json=[{"chat_id": chat_id, "job_id": jid} for jid in job_ids],
        timeout=10)

def tg_send(chat_id, text):
    try:
        requests.post(f"{TG_API}/sendMessage",
                      json={"chat_id": chat_id, "text": text,
                            "parse_mode": "HTML", "disable_web_page_preview": True},
                      timeout=10)
    except Exception as e:
        print(f"TG error {chat_id}: {e}")

def fmt_job(job):
    lines = [f"💼 <b>{job['title']}</b>", f"🏢 {job['company'] or 'Unknown'}"]

    # Location
    if job.get("location") and job["location"].lower() != "remote":
        lines.append(f"📍 {job['location']}")
    else:
        lines.append("📍 Remote")

    # Salary
    if job.get("salary"):
        lines.append(f"💰 {job['salary']}")

    # Funding / startup highlight
    if job.get("funding"):
        lines.append(f"💸 Funding: {job['funding']}")
    elif job.get("company_type") == "startup":
        lines.append("🚀 Early-stage startup")

    # Date
    if job.get("date"):
        lines.append(f"📅 {fmt_date(job['date'])}")

    lines.append(f"🔗 <a href='{job['url']}'>Apply Now</a>")
    lines.append(f"📌 via {job['source']}")
    return "\n".join(lines)

def run_scan():
    print("Fetching all jobs...")
    all_jobs = get_all_jobs()

    print("Fetching users...")
    users = get_all_users()
    print(f"Active users: {len(users)}")

    for user in users:
        chat_id = user["chat_id"]
        sent_ids = get_sent_ids(chat_id)

        matched = [j for j in all_jobs
                   if j["_id"] not in sent_ids and matches_user(j, user)]

        # Sort by score
        keywords = user.get("keywords","")
        matched.sort(key=lambda j: score(j["title"], keywords), reverse=True)
        matched = matched[:10]

        if not matched:
            print(f"User {chat_id}: no new jobs")
            continue

        print(f"User {chat_id}: sending {len(matched)} jobs")
        sources = list({j["source"] for j in matched})
        tg_send(chat_id,
            f"🔍 <b>{len(matched)} new jobs matching your profile</b>\n"
            f"Sources: {', '.join(sources)}")

        new_ids = []
        for job in matched:
            tg_send(chat_id, fmt_job(job))
            new_ids.append(job["_id"])

        mark_sent(chat_id, new_ids)

    print("Scan complete.")

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        run_scan()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Done.")
    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    run_scan()
