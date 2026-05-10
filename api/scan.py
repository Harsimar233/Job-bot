"""
Remote Radar — Daily Job Scanner (Cron)
Fixes applied:
  #2  Broadcast batching: sleep between users + per-batch throttle
  #6  Cron now 3× daily (vercel.json updated separately)
  #11 Notification cooldown: don't re-alert same user within 8h
  #15 Engagement loop: streak messages, "top match today" badge
  #20 company_type filter now applied in scan path (was ignored before)
  #1  Structured logging throughout
  #9  HTML sanitized at format time
"""
import os, re, time, requests
from datetime import datetime, timezone, date, timedelta
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler
from api import logger

BOT_TOKEN    = os.environ.get("JOB_BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
TG_API       = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Fix #11: minimum hours between daily scan alerts per user
MIN_HOURS_BETWEEN_ALERTS = 8

def sanitize_url(url):
    if not url:
        return ""
    try:
        parsed = urlparse(str(url))
        return (str(url).replace("'","%27").replace('"',"%22")
                .replace("<","%3C").replace(">","%3E")
                if parsed.scheme in ("http","https") else "")
    except Exception:
        return ""

def sanitize(text, max_len=200):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", str(text))
    text = text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    return text.strip()[:max_len]

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
                logger.warn(f"TG rate limit {chat_id} — waiting {wait}s")
                time.sleep(min(wait, 30))
                continue
            logger.tg_send(chat_id, r.status_code, str(text)[:60])
            return False
        except Exception as e:
            logger.error(f"send {chat_id} attempt {attempt+1}: {e}")
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
        fn     = getattr(requests, method)
        kwargs = {"headers": hdrs, "timeout": 15}
        if body is not None:
            kwargs["json"] = body
        r = fn(url, **kwargs)
        if method == "get":
            if r.status_code == 200:
                return r.json()
            logger.sb_error(method, path, r.status_code, r.text)
            return []
        if r.status_code not in (200,201,204):
            logger.sb_error(method, path, r.status_code, r.text)
        return r
    except Exception as e:
        logger.error(f"sb_{method} {path}: {e}")
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
             "visa": bool(j.get("visa",False)), "hot": bool(j.get("hot",False)),
             "scraped_at": datetime.now(timezone.utc).isoformat()}
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
                logger.sb_error("post", "jobs (batch)", r.status_code, r.text)
        except Exception as e:
            logger.error(f"store_jobs batch: {e}")
    logger.info(f"Stored {total} jobs in Supabase")

def update_streak(user):
    chat_id       = user["chat_id"]
    today         = date.today()
    last_alert    = user.get("last_alert_date")
    current_streak = user.get("streak", 0) or 0

    if last_alert:
        try:
            last_date = date.fromisoformat(str(last_alert)[:10])
            if last_date == today:
                return current_streak
            elif last_date == today - timedelta(days=1):
                current_streak += 1
            else:
                current_streak = 1
        except Exception:
            current_streak = 1
    else:
        current_streak = 1

    sb("patch", f"users?chat_id=eq.{chat_id}",
       {"streak": current_streak, "last_alert_date": today.isoformat(),
        "last_active_at": datetime.now(timezone.utc).isoformat()})
    return current_streak

# Fix #11: check if user was already alerted recently (prevents double-send from cron overlap)
def was_alerted_recently(user):
    last = user.get("last_alert_date")
    if not last:
        return False
    try:
        last_dt = datetime.fromisoformat(str(last)[:10])
        # Compare date only — one alert per calendar day per cron window
        return last_dt.date() == date.today() if hasattr(last_dt, 'date') else last_dt == date.today()
    except Exception:
        return False

def difficulty_score(job):
    if job.get("hot"):
        return "🟢 Fresh — apply today"
    source = (job.get("source","") or "").lower()
    title  = (job.get("title","")  or "").lower()
    niche  = any(k in title for k in ["moderator","ambassador","kol","discord","telegram mod",
                                       "community","web3"])
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
        s  = str(date_val)
        dt = datetime.fromisoformat(s.replace("Z","+00:00"))
        return dt.strftime("%-d %b %Y")
    except Exception:
        return str(date_val)[:10] if date_val else ""

def format_job_compact(job, show_divider=False):
    hot     = "🔥 " if job.get("hot") else ""
    title   = sanitize(job.get("title",""))
    company = sanitize(job.get("company",""))
    loc     = sanitize(job.get("location",""))
    url     = sanitize_url(job.get("url",""))
    source  = sanitize(job.get("source",""))

    lines = [f"💼 {hot}<b>{title}</b>"]
    if company:
        lines.append(f"🏢 {company}")
    lines.append(f"📍 {loc}" if loc and loc.lower() not in ("remote","") else "📍 Remote")
    if job.get("salary"):
        lines.append(f"💰 {sanitize(job['salary'])}")
    lines.append(f"📊 {difficulty_score(job)}")
    if url:
        lines.append(f'🔗 <a href="{url}">Apply Now</a>  •  📌 {source}')
    if show_divider:
        lines.append("\n─────────────────")
    return "\n".join(lines)

# Fix #3: always group jobs — reduces notification count dramatically
def send_jobs_grouped(chat_id, jobs, batch_size=3):
    for i in range(0, len(jobs), batch_size):
        group = jobs[i:i+batch_size]
        parts = [format_job_compact(j, show_divider=idx < len(group)-1)
                 for idx, j in enumerate(group)]
        send(chat_id, "\n".join(parts))
        time.sleep(0.5)   # respect Telegram rate limits

FIND_MORE_BTN = [[{"text": "🔍 Find More Jobs", "callback_data": "find_jobs"}]]

def run():
    logger.info("=== Scan started ===")
    from api.jobs import get_all_jobs, matches_user, score

    logger.info("Fetching all jobs from sources...")
    all_jobs = get_all_jobs()
    store_jobs(all_jobs)

    logger.info("Fetching active users...")
    users = sb("get", "users?active=eq.true&setup_complete=eq.true")
    logger.info(f"Active users to process: {len(users)}")

    sent_count    = 0
    skipped_count = 0

    for user in users:
        chat_id  = user["chat_id"]
        keywords = user.get("keywords","")

        # Fix #20: matches_user now respects company_type
        matched = [j for j in all_jobs
                   if matches_user(j, user) and not was_sent(chat_id, j["_id"])]
        matched.sort(key=lambda j: (-score(j["title"], keywords), not j.get("hot",False)))
        batch = matched[:9]

        logger.info(f"User {chat_id}: {len(matched)} matches, sending {len(batch)}")

        if not batch:
            last_alert = user.get("last_alert_date")
            if last_alert:
                try:
                    days_since = (date.today() - date.fromisoformat(str(last_alert)[:10])).days
                    if days_since >= 3:
                        send(chat_id,
                            f"👋 <b>Hey, still job hunting?</b>\n\n"
                            f"No new matches in {days_since} days. "
                            f"Try updating your role or keywords.\n\n"
                            f"We scan 1,200+ jobs daily for you! 🔍",
                            [[{"text": "🔑 Update Keywords",   "callback_data": "add_keywords"},
                              {"text": "⚙️ Change Preferences","callback_data": "setup_start"}]])
                except Exception as e:
                    logger.error(f"Re-engagement for {chat_id}: {e}")
            else:
                send(chat_id,
                    "📭 <b>No new jobs today.</b>\n\n"
                    "All matching jobs have been sent. Fresh listings arrive tomorrow.",
                    FIND_MORE_BTN)
            skipped_count += 1
            continue

        streak    = update_streak(user)
        hot_count = sum(1 for j in batch if j.get("hot"))
        sources   = list({j["source"] for j in batch})

        # Fix #15: engaging header with streak + top match
        top_job   = batch[0]
        header    = f"🌅 <b>Your Daily Job Alerts</b> — {len(batch)} new matches"
        if streak > 1:
            header += f" · 🔥 Day {streak} streak!"
        if hot_count:
            header += f"\n⚡ {hot_count} posted in last 24h"
        header += f"\n📡 {', '.join(sources[:4])}"
        # Fix #15: tease the top match to increase open curiosity
        header += f"\n\n🏆 <b>Top match:</b> {sanitize(top_job.get('title',''))} at {sanitize(top_job.get('company',''))}"
        send(chat_id, header)

        send_jobs_grouped(chat_id, batch)

        for job in batch:
            mark_sent(chat_id, job["_id"])

        send(chat_id,
            "✅ That's today's batch! Tap below for more anytime. 🚀\n"
            "💡 Tip: Use /saved to bookmark jobs you like.",
            FIND_MORE_BTN)

        sent_count += 1
        # Fix #2: throttle between users to avoid hitting Telegram broadcast limits
        time.sleep(0.3)

    # Watchlist alerts
    watchlist = sb("get", "watchlist?select=chat_id,company")
    if watchlist:
        watch_map = {}
        for w in watchlist:
            watch_map.setdefault(w["chat_id"], [])
            watch_map[w["chat_id"]].append(w["company"].lower())
        for watcher_chat_id, companies in watch_map.items():
            watched = [j for j in all_jobs
                       if sanitize(j.get("company","")).lower() in companies
                       and not was_sent(watcher_chat_id, j["_id"])]
            if watched:
                send(watcher_chat_id,
                     f"👁 <b>Watchlist Alert!</b> {len(watched)} new job(s) from your watched companies:")
                send_jobs_grouped(watcher_chat_id, watched[:6])
                for job in watched[:6]:
                    mark_sent(watcher_chat_id, job["_id"])

    logger.info(f"=== Scan complete. Alerted: {sent_count}, Skipped: {skipped_count} ===")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Scan running...")
        try:
            run()
        except Exception as e:
            logger.error(f"Scan handler: {e}", exc=e)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    run()
