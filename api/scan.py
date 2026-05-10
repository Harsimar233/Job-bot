"""
Remote Radar — Daily Job Scanner
Production: grouped messages, rate limiting, error logging, retry logic.
"""
import os, re, time, requests
from datetime import datetime, timezone
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler

BOT_TOKEN    = os.environ.get("JOB_BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def sanitize_url(url):
    if not url:
        return ""
    try:
        parsed = urlparse(str(url))
        if parsed.scheme not in ("http","https"):
            return ""
        return str(url).replace("'","%27").replace('"',"%22")
    except Exception:
        return ""

def sanitize_text(text):
    if not text:
        return ""
    return re.sub(r"<[^>]+>","",str(text)).strip()[:200]

def send(chat_id, text, buttons=None, retries=3):
    payload = {"chat_id": chat_id, "text": str(text)[:4096],
                "parse_mode": "HTML", "disable_web_page_preview": True}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    for attempt in range(retries):
        try:
            r = requests.post(f"{TG_API}/sendMessage", json=payload, timeout=10)
            if r.status_code == 200:
                return True
            if r.status_code == 429:
                wait = r.json().get("parameters",{}).get("retry_after",5)
                log(f"Rate limited — waiting {wait}s")
                time.sleep(wait)
                continue
            log(f"Send failed {r.status_code}: {r.text[:100]}")
            return False
        except Exception as e:
            log(f"Send error: {e}")
            if attempt < retries - 1:
                time.sleep(1)
    return False

def sb_get(path):
    hdrs = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    url = SUPABASE_URL.rstrip("/") + "/rest/v1/" + path
    try:
        r = requests.get(url, headers=hdrs, timeout=10)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        log(f"sb_get error {path}: {e}")
        return []

def sb_post(path, body, prefer="resolution=ignore-duplicates"):
    hdrs = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json", "Prefer": prefer}
    url = SUPABASE_URL.rstrip("/") + "/rest/v1/" + path
    try:
        r = requests.post(url, headers=hdrs, json=body, timeout=15)
        if r.status_code not in (200, 201):
            log(f"sb_post error {r.status_code} {path}: {r.text[:100]}")
    except Exception as e:
        log(f"sb_post error {path}: {e}")

def was_sent(chat_id, job_id):
    r = sb_get(f"sent_jobs?chat_id=eq.{chat_id}&job_id=eq.{job_id}&select=id&limit=1")
    return bool(r)

def mark_sent(chat_id, job_id):
    sb_post("sent_jobs", {"chat_id": chat_id, "job_id": str(job_id)})

def store_jobs(jobs):
    if not jobs:
        return
    rows = []
    for j in jobs:
        rows.append({
            "job_id": j["_id"],
            "title": sanitize_text(j.get("title","")),
            "company": sanitize_text(j.get("company","")),
            "url": sanitize_url(j.get("url","")),
            "source": sanitize_text(j.get("source","")),
            "date_posted": str(j.get("date","")),
            "location": sanitize_text(j.get("location","Remote")),
            "salary": sanitize_text(j.get("salary","")),
            "funding": sanitize_text(j.get("funding","")),
            "company_type": j.get("company_type",""),
            "visa": bool(j.get("visa", False)),
            "hot": bool(j.get("hot", False)),
        })
    hdrs = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal"}
    url = SUPABASE_URL.rstrip("/") + "/rest/v1/jobs"
    total = 0
    for i in range(0, len(rows), 100):
        batch = rows[i:i+100]
        try:
            r = requests.post(url, headers=hdrs, json=batch, timeout=30)
            if r.status_code in (200, 201):
                total += len(batch)
            else:
                log(f"store_jobs batch error: {r.status_code} {r.text[:200]}")
        except Exception as e:
            log(f"store_jobs error: {e}")
    log(f"Stored {total} jobs in Supabase")

def fmt_date(date_val):
    if not date_val:
        return ""
    try:
        s = str(date_val)
        dt = datetime.fromisoformat(s.replace("Z","+00:00"))
        return dt.strftime("%-d %b %Y")
    except Exception:
        try:
            s = str(date_val)
            return s[:10] if len(s) >= 10 else s
        except Exception:
            return ""

def format_job_compact(job, show_divider=False):
    hot = "🔥 " if job.get("hot") else ""
    title = sanitize_text(job.get("title",""))
    company = sanitize_text(job.get("company",""))
    loc = sanitize_text(job.get("location",""))
    url = sanitize_url(job.get("url",""))
    source = sanitize_text(job.get("source",""))

    lines = [f"💼 {hot}<b>{title}</b>"]
    if company:
        lines.append(f"🏢 {company}")
    if loc and loc.lower() not in ("remote",""):
        lines.append(f"📍 {loc}")
    else:
        lines.append("📍 Remote")
    if job.get("salary"):
        lines.append(f"💰 {sanitize_text(job['salary'])}")
    if job.get("funding"):
        lines.append(f"💸 {sanitize_text(job['funding'])}")
    if job.get("visa"):
        lines.append("✈️ Visa sponsorship")
    d = fmt_date(job.get("date",""))
    if d:
        lines.append(f"📅 {d}")
    if url:
        lines.append(f"🔗 <a href='{url}'>Apply Now</a>  •  📌 {source}")
    if show_divider:
        lines.append("\n─────────────────")
    return "\n".join(lines)

def send_jobs_grouped(chat_id, jobs, batch_size=3):
    for i in range(0, len(jobs), batch_size):
        group = jobs[i:i+batch_size]
        parts = []
        for idx, job in enumerate(group):
            parts.append(format_job_compact(job, show_divider=idx < len(group)-1))
        send(chat_id, "\n".join(parts))
        time.sleep(0.5)  # Prevent rate limiting during broadcasts

FIND_MORE_BTN = [[{"text": "🔍 Find More Jobs", "callback_data": "find_jobs"}]]

def run():
    log("Fetching all jobs...")
    from api.jobs import get_all_jobs, matches_user, score

    all_jobs = get_all_jobs()

    # Store all jobs in Supabase
    store_jobs(all_jobs)

    log("Fetching users...")
    users = sb_get("users?active=eq.true&setup_complete=eq.true")
    log(f"Active users: {len(users)}")

    for user in users:
        chat_id = user["chat_id"]
        keywords = user.get("keywords","")

        matched = [j for j in all_jobs if matches_user(j, user) and not was_sent(chat_id, j["_id"])]
        matched.sort(key=lambda j: (-score(j["title"], keywords), not j.get("hot", False)))
        batch = matched[:9]  # 9 = 3 groups of 3

        log(f"User {chat_id}: {len(batch)} new jobs")

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
        header += f"\n📡 {', '.join(sources[:4])}"
        send(chat_id, header)

        send_jobs_grouped(chat_id, batch)

        for job in batch:
            mark_sent(chat_id, job["_id"])

        send(chat_id, "✅ That's today's batch! Tap below anytime for more. 🚀", FIND_MORE_BTN)

        time.sleep(0.5)  # Space between users

    # Watchlist alerts
    watchlist = sb_get("watchlist?select=chat_id,company")
    if watchlist:
        watch_map = {}
        for w in watchlist:
            watch_map.setdefault(w["chat_id"], [])
            watch_map[w["chat_id"]].append(w["company"].lower())

        for chat_id, companies in watch_map.items():
            watched = [j for j in all_jobs
                       if sanitize_text(j.get("company","")).lower() in companies
                       and not was_sent(chat_id, j["_id"])]
            if watched:
                send(chat_id,
                    f"👁 <b>Watchlist Alert!</b> {len(watched)} new job(s) from your watched companies:")
                send_jobs_grouped(chat_id, watched[:6])
                for job in watched[:6]:
                    mark_sent(chat_id, job["_id"])

    log("Scan complete.")


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
