"""
Remote Radar — Daily Job Scanner
Fetches all jobs, stores in Supabase, sends personalized alerts.
"""
import os, requests, json
from datetime import datetime
from http.server import BaseHTTPRequestHandler

BOT_TOKEN    = os.environ.get("JOB_BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send(chat_id, text, buttons=None):
    payload = {
        "chat_id": chat_id, "text": str(text)[:4096],
        "parse_mode": "HTML", "disable_web_page_preview": True,
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    try:
        requests.post(f"{TG_API}/sendMessage", json=payload, timeout=10)
    except Exception:
        pass

def sb_get(path):
    hdrs = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    url = SUPABASE_URL.rstrip("/") + "/rest/v1/" + path
    try:
        r = requests.get(url, headers=hdrs, timeout=10)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []

def sb_post(path, body, upsert=False):
    hdrs = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates" if upsert else "resolution=ignore-duplicates",
    }
    url = SUPABASE_URL.rstrip("/") + "/rest/v1/" + path
    try:
        requests.post(url, headers=hdrs, json=body, timeout=10)
    except Exception:
        pass

def was_sent(chat_id, job_id):
    r = sb_get(f"sent_jobs?chat_id=eq.{chat_id}&job_id=eq.{job_id}&select=id&limit=1")
    return bool(r)

def mark_sent(chat_id, job_id):
    sb_post("sent_jobs", {"chat_id": chat_id, "job_id": str(job_id)})

def store_jobs(jobs):
    """Store all scraped jobs in Supabase for instant retrieval later."""
    if not jobs:
        return
    rows = []
    for j in jobs:
        rows.append({
            "job_id": j["_id"],
            "title": j.get("title",""),
            "company": j.get("company",""),
            "url": j.get("url",""),
            "source": j.get("source",""),
            "date_posted": str(j.get("date","")),
            "location": j.get("location","Remote"),
            "salary": j.get("salary",""),
            "funding": j.get("funding",""),
            "company_type": j.get("company_type",""),
            "visa": bool(j.get("visa", False)),
            "hot": bool(j.get("hot", False)),
        })
    hdrs = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    url = SUPABASE_URL.rstrip("/") + "/rest/v1/jobs"
    total = 0
    for i in range(0, len(rows), 100):
        batch = rows[i:i+100]
        try:
            r = requests.post(url, headers=hdrs, json=batch, timeout=30)
            if r.status_code in (200, 201):
                total += len(batch)
            else:
                print(f"store_jobs batch error: {r.status_code} {r.text[:200]}")
        except Exception as e:
            print(f"store_jobs error: {e}")
    print(f"Stored {total} jobs in Supabase")

def fmt_date(date_val):
    if not date_val:
        return ""
    try:
        s = str(date_val)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%-d %b %Y")
    except Exception:
        try:
            s = str(date_val)
            return s[:10] if len(s) >= 10 else s
        except Exception:
            return ""

def format_job(job):
    hot = "🔥 " if job.get("hot") else ""
    lines = [f"💼 {hot}<b>{job.get('title','')}</b>"]
    if job.get("company"):
        lines.append(f"🏢 {job['company']}")
    loc = job.get("location","")
    if loc and loc.lower() not in ("remote",""):
        lines.append(f"📍 {loc}")
    else:
        lines.append("📍 Remote")
    if job.get("salary"):
        lines.append(f"💰 {job['salary']}")
    if job.get("funding"):
        lines.append(f"💸 Funding: {job['funding']}")
    if job.get("visa"):
        lines.append("✈️ Visa sponsorship available")
    d = fmt_date(job.get("date") or job.get("date_posted",""))
    if d:
        lines.append(f"📅 {d}")
    url = job.get("url","")
    if url:
        lines.append(f"🔗 <a href='{url}'>Apply Now</a>")
    lines.append(f"📌 {job.get('source','')}")
    return "\n".join(lines)

FIND_MORE_BTN = [[{"text": "🔍 Find More Jobs", "callback_data": "find_jobs"}]]

def run():
    print("Fetching all jobs...")
    from api.jobs import get_all_jobs, matches_user, score

    all_jobs = get_all_jobs()

    # Store all jobs in Supabase for instant retrieval
    store_jobs(all_jobs)

    print("Fetching users...")
    users = sb_get("users?active=eq.true&setup_complete=eq.true")
    print(f"Active users: {len(users)}")

    for user in users:
        chat_id = user["chat_id"]
        keywords = user.get("keywords", "")

        matched = [j for j in all_jobs
                   if matches_user(j, user) and not was_sent(chat_id, j["_id"])]
        matched.sort(key=lambda j: (-score(j["title"], keywords), not j.get("hot", False)))
        batch = matched[:10]

        print(f"User {chat_id}: {len(batch)} new jobs")

        if not batch:
            send(chat_id,
                "📭 <b>No new jobs today.</b>\n\n"
                "All matching jobs have already been sent. "
                "Fresh listings arrive tomorrow at 9am UTC.",
                FIND_MORE_BTN)
            continue

        hot_count = sum(1 for j in batch if j.get("hot"))
        sources = list({j["source"] for j in batch})

        header = f"🌅 <b>Your Daily Job Alerts</b> — {len(batch)} new matches"
        if hot_count:
            header += f" · 🔥 {hot_count} posted today"
        header += f"\n📡 {', '.join(sources)}"
        send(chat_id, header)

        for job in batch:
            send(chat_id, format_job(job))
            mark_sent(chat_id, job["_id"])

        send(chat_id,
            "✅ That's today's batch! Tap below to get more anytime. 🚀",
            FIND_MORE_BTN)

    # Watchlist alerts
    watchlist = sb_get("watchlist?select=chat_id,company")
    if watchlist:
        watch_map = {}
        for w in watchlist:
            cid = w["chat_id"]
            watch_map.setdefault(cid, [])
            watch_map[cid].append(w["company"].lower())

        for chat_id, companies in watch_map.items():
            watched_jobs = [j for j in all_jobs
                            if j.get("company","").lower() in companies
                            and not was_sent(chat_id, j["_id"])]
            if watched_jobs:
                send(chat_id,
                    f"👁 <b>Watchlist Alert!</b> {len(watched_jobs)} new job(s) from companies you're tracking:")
                for job in watched_jobs[:5]:
                    send(chat_id, format_job(job))
                    mark_sent(chat_id, job["_id"])

    print("Scan complete.")


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
