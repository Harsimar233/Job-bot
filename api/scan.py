"""
Remote Radar — Daily Job Scanner
Runs via GitHub Actions at 9am UTC daily.
Sends personalized alerts to all active users + watchlist notifications.
"""
import os, requests
from http.server import BaseHTTPRequestHandler

BOT_TOKEN    = os.environ.get("JOB_BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send(chat_id, text, buttons=None):
    payload = {
        "chat_id": chat_id, "text": text[:4096],
        "parse_mode": "HTML", "disable_web_page_preview": True,
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    try:
        requests.post(f"{TG_API}/sendMessage", json=payload, timeout=10)
    except Exception:
        pass

def sb_get(path, params=None):
    hdrs = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    url = SUPABASE_URL.rstrip("/") + "/rest/v1/" + path
    try:
        r = requests.get(url, headers=hdrs, params=params, timeout=10)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []

def sb_post(path, body):
    hdrs = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json", "Prefer": "return=representation"}
    url = SUPABASE_URL.rstrip("/") + "/rest/v1/" + path
    try:
        requests.post(url, headers=hdrs, json=body, timeout=10)
    except Exception:
        pass

def was_sent(chat_id, job_id):
    r = sb_get(f"sent_jobs?chat_id=eq.{chat_id}&job_id=eq.{job_id}")
    return bool(r)

def mark_sent(chat_id, job_id):
    sb_post("sent_jobs", {"chat_id": chat_id, "job_id": job_id})

def get_watchlist_users():
    """Get all watchlist entries"""
    return sb_get("watchlist?select=chat_id,company")

def format_job(job):
    hot = "🔥 " if job.get("hot") else ""
    title = f"{hot}<b>{job['title']}</b>"
    company = f"🏢 {job['company']}" if job.get("company") else ""
    loc = f"\n📍 {job['location']}" if job.get("location") and job["location"].lower() not in ("remote","") else ""
    sal = f"\n💰 {job['salary']}" if job.get("salary") else ""
    fund = f"\n💸 Funding: {job['funding']}" if job.get("funding") else ""
    visa = "\n✈️ Visa sponsorship" if job.get("visa") else ""
    date = f"\n📅 {fmt_date(job['date'])}" if job.get("date") else ""

    lines = [f"💼 {title}"]
    if company: lines.append(company)
    if loc: lines.append(loc)
    if sal: lines.append(sal)
    if fund: lines.append(fund)
    if visa: lines.append(visa)
    if date: lines.append(date)
    lines.append(f"🔗 <a href='{job.get('url','')}'>Apply Now</a>")
    lines.append(f"📌 {job['source']}")
    return "\n".join(lines)

def fmt_date(date_str):
    if not date_str: return ""
    from datetime import datetime
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return dt.strftime("%d %b %Y")
    except Exception:
        return date_str[:10]

FIND_MORE_BTN = [[{"text": "🔍 Find More Jobs", "callback_data": "find_now"}]]

def run():
    print("Fetching all jobs...")
    from api.jobs import get_all_jobs, matches_user, score

    all_jobs = get_all_jobs()

    # ── Regular user alerts ───────────────────────────────────────────────────
    print("Fetching users...")
    users = sb_get("users?active=eq.true&setup_complete=eq.true")
    print(f"Active users: {len(users)}")

    for user in users:
        chat_id = user["chat_id"]
        keywords = user.get("keywords", "")

        # Filter matching + unsent jobs
        matched = [j for j in all_jobs
                   if matches_user(j, user) and not was_sent(chat_id, j["_id"])]
        matched.sort(key=lambda j: (-score(j["title"], keywords), not j.get("hot")))
        batch = matched[:10]

        print(f"User {chat_id}: sending {len(batch)} jobs")

        if not batch:
            send(chat_id,
                 "✅ <b>All caught up!</b>\n\nNo new matching jobs found today. "
                 "I'll alert you as soon as fresh ones arrive.\n\n"
                 "Use /find to search on demand or /market to see today's trends.",
                 FIND_MORE_BTN)
            continue

        hot_count = sum(1 for j in batch if j.get("hot"))
        sources = list({j["source"] for j in batch})

        header = f"🌅 <b>Your Daily Job Alerts</b> — {len(batch)} new matches"
        if hot_count:
            header += f" · 🔥 {hot_count} hot"
        header += f"\n📡 {', '.join(sources)}"
        send(chat_id, header)

        for job in batch:
            send(chat_id, format_job(job))
            mark_sent(chat_id, job["id"])

        send(chat_id,
             "That's today's batch! See you tomorrow with fresh listings. 🚀\n"
             "Use /find anytime for on-demand search.",
             FIND_MORE_BTN)

    # ── Watchlist alerts ──────────────────────────────────────────────────────
    watchlist_entries = get_watchlist_users()
    if watchlist_entries:
        # Group by chat_id
        watch_map = {}
        for w in watchlist_entries:
            cid = w["chat_id"]
            if cid not in watch_map:
                watch_map[cid] = []
            watch_map[cid].append(w["company"].lower())

        for chat_id, companies in watch_map.items():
            watched_jobs = [j for j in all_jobs
                            if j.get("company", "").lower() in companies
                            and not was_sent(chat_id, j["id"])]
            if watched_jobs:
                send(chat_id, f"👁 <b>Watchlist Alert!</b> {len(watched_jobs)} new job(s) from companies you're watching:")
                for job in watched_jobs[:5]:
                    send(chat_id, format_job(job))
                    mark_sent(chat_id, job["id"])

    print("Scan complete.")


# Vercel serverless function entry point
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Running scan...")
        run()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    run()
