"""
Daily Job Scanner — runs for ALL users via GitHub Actions.
Fetches jobs, matches to each user's preferences, sends alerts.
"""
import os, json, requests
from http.server import BaseHTTPRequestHandler
from api.jobs import get_all_jobs, matches_user, fmt_date, score

BOT_TOKEN    = os.environ.get("JOB_BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ── Supabase ──────────────────────────────────────────────────────────────────

def get_all_users():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?active=eq.true&setup_complete=eq.true&select=*",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
        timeout=10
    )
    return r.json() if r.status_code == 200 else []

def get_sent_ids(chat_id):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/sent_jobs?chat_id=eq.{chat_id}&select=job_id",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
        timeout=10
    )
    if r.status_code == 200:
        return {row["job_id"] for row in r.json()}
    return set()

def mark_sent(chat_id, job_ids):
    if not job_ids:
        return
    rows = [{"chat_id": chat_id, "job_id": jid} for jid in job_ids]
    requests.post(
        f"{SUPABASE_URL}/rest/v1/sent_jobs",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=ignore-duplicates",
        },
        json=rows,
        timeout=10
    )

# ── Telegram ──────────────────────────────────────────────────────────────────

def tg_send(chat_id, text):
    try:
        requests.post(
            f"{TG_API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10
        )
    except Exception as e:
        print(f"TG send error: {e}")

def fmt_job(job, rank):
    date_label = f"\n📅 {fmt_date(job['date'])}" if job.get("date") else ""
    loc_label = f"\n📍 {job['location']}" if job.get("location") and job["location"] != "Remote" else ""
    return (
        f"💼 <b>{job['title']}</b>\n"
        f"🏢 {job['company'] or 'Unknown'}"
        f"{loc_label}{date_label}\n"
        f"🔗 <a href='{job['url']}'>Apply Now</a>\n"
        f"📌 via {job['source']}"
    )

# ── Main scan ─────────────────────────────────────────────────────────────────

def run_scan():
    print("Fetching all jobs...")
    all_jobs = get_all_jobs()

    print("Fetching all users...")
    users = get_all_users()
    print(f"Active users: {len(users)}")

    for user in users:
        chat_id = user["chat_id"]
        keywords = user.get("keywords", "community,marketing,support")
        location = user.get("location", "Remote")
        remote_only = user.get("remote_only", True)

        # Get jobs already sent to this user
        sent_ids = get_sent_ids(chat_id)

        # Filter jobs for this user
        matched = []
        for job in all_jobs:
            if job["_id"] in sent_ids:
                continue
            if matches_user(job, keywords, location, remote_only):
                matched.append(job)

        matched = matched[:10]  # Max 10 per user per day

        if not matched:
            print(f"User {chat_id}: no new matching jobs")
            continue

        print(f"User {chat_id}: sending {len(matched)} jobs")

        # Send header
        sources = list({j["source"] for j in matched})
        tg_send(chat_id,
            f"🔍 <b>{len(matched)} new remote jobs for you today</b>\n"
            f"Sources: {', '.join(sources)}"
        )

        # Send each job
        new_ids = []
        for i, job in enumerate(matched, 1):
            tg_send(chat_id, fmt_job(job, i))
            new_ids.append(job["_id"])

        # Mark as sent
        mark_sent(chat_id, new_ids)

    print("Scan complete.")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        run_scan()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Scan complete.")

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    run_scan()
