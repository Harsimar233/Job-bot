"""
Remote Radar — Daily Job Scanner
Features: streak tracking, re-engagement, grouped messages, watchlist alerts.
"""
import os, re, time, requests
from datetime import datetime, timezone, date, timedelta
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
        return str(url).replace("'","%27").replace('"',"%22") if parsed.scheme in ("http","https") else ""
    except Exception:
        return ""

def sanitize(text, max_len=200):
    if not text:
        return ""
    return re.sub(r"<[^>]+>","",str(text)).strip()[:max_len]

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
            log(f"Send failed {r.status_code}")
            return False
        except Exception as e:
            log(f"Send error: {e}")
            if attempt < retries - 1:
                time.sleep(1)
    return False

def sb(method, path, body=None, prefer=None):
    hdrs = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"}
    if prefer:
        hdrs["Prefer"] = prefer
    url = SUPABASE_URL.rstrip("/") + "/rest/v1/" + path
    try:
        fn = getattr(requests, method)
        kwargs = {"headers": hdrs, "timeout": 15}
        if body is not None:
            kwargs["json"] = body
        r = fn(url, **kwargs)
        if method == "get":
            return r.json() if r.status_code == 200 else []
        if r.status_code not in (200,201,204):
            log(f"sb_{method} {r.status_code} {path}: {r.text[:100]}")
        return r
    except Exception as e:
        log(f"sb_{method} error {path}: {e}")
        return [] if method == "get" else None

def was_sent(chat_id, job_id):
    r = sb("get", f"sent_jobs?chat_id=eq.{chat_id}&job_id=eq.{job_id}&select=id&limit=1")
    return bool(r)

def mark_sent(chat_id, job_id):
    sb("post", "sent_jobs", {"chat_id": chat_id, "job_id": str(job_id)},
       prefer="resolution=ignore-duplicates")

def store_jobs(jobs):
    if not jobs:
        return
    rows = [{"job_id": j["_id"], "title": sanitize(j.get("title","")),
             "company": sanitize(j.get("company","")), "url": sanitize_url(j.get("url","")),
             "source": sanitize(j.get("source","")), "date_posted": str(j.get("date","")),
             "location": sanitize(j.get("location","Remote")), "salary": sanitize(j.get("salary","")),
             "funding": sanitize(j.get("funding","")), "company_type": j.get("company_type",""),
             "visa": bool(j.get("visa",False)), "hot": bool(j.get("hot",False))}
            for j in jobs]
    hdrs = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal"}
    url = SUPABASE_URL.rstrip("/") + "/rest/v1/jobs"
    total = 0
    for i in range(0, len(rows), 100):
        try:
            r = requests.post(url, headers=hdrs, json=rows[i:i+100], timeout=30)
            if r.status_code in (200,201):
                total += len(rows[i:i+100])
            else:
                log(f"store_jobs error: {r.status_code} {r.text[:100]}")
        except Exception as e:
            log(f"store_jobs exception: {e}")
    log(f"Stored {total} jobs in Supabase")

def update_streak(user):
    """Calculate and update user's consecutive daily streak."""
    chat_id = user["chat_id"]
    today = date.today()
    last_alert = user.get("last_alert_date")
    current_streak = user.get("streak", 0) or 0

    if last_alert:
        try:
            last_date = date.fromisoformat(str(last_alert)[:10])
            if last_date == today:
                return current_streak  # Already updated today
            elif last_date == today - timedelta(days=1):
                current_streak += 1  # Consecutive day
            else:
                current_streak = 1  # Streak broken
        except Exception:
            current_streak = 1
    else:
        current_streak = 1

    sb("patch", f"users?chat_id=eq.{chat_id}",
       {"streak": current_streak, "last_alert_date": today.isoformat(),
        "last_active_at": datetime.now(timezone.utc).isoformat()})
    return current_streak

def difficulty_score(job):
    if job.get("hot"):
        return "🟢 Fresh — apply today"
    source = (job.get("source","") or "").lower()
    title = (job.get("title","") or "").lower()
    niche = any(k in title for k in ["moderator","ambassador","kol","discord","telegram mod","community","web3"])
    big_co = any(s in source for s in ["greenhouse","lever","ashby"])
    if big_co and not niche:
        return "🔴 Competitive role"
    if niche:
        return "🟢 Niche — apply fast"
    return "🟡 Moderate competition"

def fmt_date(date_val):
    if not date_val:
        return ""
    try:
        s = str(date_val)
        dt = datetime.fromisoformat(s.replace("Z","+00:00"))
        return dt.strftime("%-d %b %Y")
    except Exception:
        try:
            return str(date_val)[:10]
        except Exception:
            return ""

def format_job_compact(job, show_divider=False):
    hot = "🔥 " if job.get("hot") else ""
    title = sanitize(job.get("title",""))
    company = sanitize(job.get("company",""))
    loc = sanitize(job.get("location",""))
    url = sanitize_url(job.get("url",""))
    source = sanitize(job.get("source",""))

    lines = [f"💼 {hot}<b>{title}</b>"]
    if company:
        lines.append(f"🏢 {company}")
    lines.append(f"📍 {loc}" if loc and loc.lower() not in ("remote","") else "📍 Remote")
    if job.get("salary"):
        lines.append(f"💰 {sanitize(job['salary'])}")
    lines.append(f"📊 {difficulty_score(job)}")
    if url:
        lines.append(f"🔗 <a href='{url}'>Apply Now</a>  •  📌 {source}")
    if show_divider:
        lines.append("\n─────────────────")
    return "\n".join(lines)

def send_jobs_grouped(chat_id, jobs, batch_size=3):
    for i in range(0, len(jobs), batch_size):
        group = jobs[i:i+batch_size]
        parts = [format_job_compact(j, show_divider=idx < len(group)-1)
                 for idx, j in enumerate(group)]
        send(chat_id, "\n".join(parts))
        time.sleep(0.5)

FIND_MORE_BTN = [[{"text": "🔍 Find More Jobs", "callback_data": "find_jobs"}]]

def run():
    log("Fetching all jobs...")
    from api.jobs import get_all_jobs, matches_user, score

    all_jobs = get_all_jobs()
    store_jobs(all_jobs)

    log("Fetching users...")
    users = sb("get", "users?active=eq.true&setup_complete=eq.true")
    log(f"Active users: {len(users)}")

    for user in users:
        chat_id = user["chat_id"]
        keywords = user.get("keywords","")

        matched = [j for j in all_jobs if matches_user(j, user) and not was_sent(chat_id, j["_id"])]
        matched.sort(key=lambda j: (-score(j["title"], keywords), not j.get("hot",False)))
        batch = matched[:9]

        log(f"User {chat_id}: {len(batch)} new jobs")

        if not batch:
            # Re-engagement: check last alert date
            last_alert = user.get("last_alert_date")
            if last_alert:
                try:
                    days_since = (date.today() - date.fromisoformat(str(last_alert)[:10])).days
                    if days_since >= 3:
                        # Send re-engagement nudge
                        send(chat_id,
                            f"👋 <b>Hey, still job hunting?</b>\n\n"
                            f"You haven't had new matches in {days_since} days. "
                            f"Try updating your role or keywords to get fresh results.\n\n"
                            f"We're scanning 1,200+ jobs daily for you! 🔍",
                            [[{"text": "🔑 Update Keywords", "callback_data": "add_keywords"},
                              {"text": "⚙️ Change Preferences", "callback_data": "setup_start"}]])
                except Exception:
                    pass
            else:
                send(chat_id,
                    "📭 <b>No new jobs today.</b>\n\n"
                    "All matching jobs have been sent. Fresh listings arrive tomorrow.",
                    FIND_MORE_BTN)
            continue

        # Update streak
        streak = update_streak(user)

        hot_count = sum(1 for j in batch if j.get("hot"))
        sources = list({j["source"] for j in batch})

        header = f"🌅 <b>Your Daily Job Alerts</b> — {len(batch)} new matches"
        if streak > 1:
            header += f" · 🔥 Day {streak} streak!"
        if hot_count:
            header += f"\n⚡ {hot_count} posted today"
        header += f"\n📡 {', '.join(sources[:4])}"
        send(chat_id, header)

        send_jobs_grouped(chat_id, batch)

        for job in batch:
            mark_sent(chat_id, job["_id"])

        send(chat_id,
            "✅ That's today's batch! Tap below for more anytime. 🚀\n"
            "Tip: Use /saved to bookmark jobs you like.",
            FIND_MORE_BTN)

        time.sleep(0.5)

    # Watchlist alerts
    watchlist = sb("get", "watchlist?select=chat_id,company")
    if watchlist:
        watch_map = {}
        for w in watchlist:
            watch_map.setdefault(w["chat_id"], [])
            watch_map[w["chat_id"]].append(w["company"].lower())
        for chat_id, companies in watch_map.items():
            watched = [j for j in all_jobs
                       if sanitize(j.get("company","")).lower() in companies
                       and not was_sent(chat_id, j["_id"])]
            if watched:
                send(chat_id, f"👁 <b>Watchlist Alert!</b> {len(watched)} new job(s) from your watched companies:")
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
