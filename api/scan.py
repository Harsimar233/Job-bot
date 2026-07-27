"""
Super Job Bot — Daily Job Scanner (Cron)
Fixes applied:
  #1  Structured logging throughout
  #2  Broadcast sleep reduced 10× — won't timeout on Vercel
  #6  Cron runs 3× daily (vercel.json handles schedule)
  #9  HTML sanitized at format time
  #11 Notification cooldown: 6-hour window so all 3 crons can fire, but same cron won't double-send
  #15 Engagement loop: streak messages, top match teaser
  #20 company_type filter applied in scan path
  #FB Feedback loop: liked/disliked jobs boost or suppress results
"""
import os, re, time, requests
from datetime import datetime, timezone, date, timedelta
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler
from api import logger

BOT_TOKEN    = os.environ.get("JOB_BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
CRON_SECRET  = os.environ.get("CRON_SECRET", "")
TG_API       = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Minimum hours between alerts per user — 6h allows all 3 crons (9am/3pm/9pm)
# but prevents a single cron from double-firing if Vercel retries
MIN_HOURS_BETWEEN_ALERTS = 5.5

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
             "description": sanitize(j.get("desc",""), max_len=600),
             "funding": sanitize(j.get("funding","")), "company_type": j.get("company_type",""),
             "work_mode": sanitize(j.get("work_mode","unknown")),
             "employment_type": sanitize(j.get("employment_type","unknown")),
             "category": sanitize(j.get("category","")),
             "experience": sanitize(j.get("experience","")),
             "apply_method": sanitize(j.get("apply_method","url")),
             "discovery_method": sanitize(j.get("discovery_method","scraper")),
             "evidence": sanitize(j.get("evidence",""), max_len=300),
             "visa_status": sanitize(j.get("visa_status","unknown")),
             "visa": bool(j.get("visa",False)),
             "overseas_candidates": bool(j.get("overseas_candidates",False)),
             "hot": bool(j.get("hot",False)),
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
    chat_id        = user["chat_id"]
    today          = date.today()
    last_alert     = user.get("last_alert_date")
    current_streak = user.get("streak", 0) or 0

    if last_alert:
        try:
            last_date = date.fromisoformat(str(last_alert)[:10])
            if last_date == today:
                return current_streak          # already updated today — don't double-increment
            elif last_date == today - timedelta(days=1):
                current_streak += 1            # consecutive day → extend streak
            else:
                current_streak = 1             # gap → restart streak
        except Exception:
            current_streak = 1
    else:
        current_streak = 1

    sb("patch", f"users?chat_id=eq.{chat_id}",
       {"streak": current_streak,
        "last_alert_date": datetime.now(timezone.utc).isoformat(),  # full datetime, not just date
        "last_active_at":  datetime.now(timezone.utc).isoformat()})
    return current_streak

def was_alerted_recently(user):
    """
    Returns True only if this user was alerted within the last MIN_HOURS_BETWEEN_ALERTS hours.
    Using a full datetime (not just date) means the 9am, 3pm and 9pm crons can all fire,
    but if Vercel retries a cron within 6h it won't double-send.
    """
    last = user.get("last_alert_date")
    if not last:
        return False
    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        hours_ago = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
        return hours_ago < MIN_HOURS_BETWEEN_ALERTS
    except Exception:
        return False

def get_user_feedback(chat_id):
    """Return sets of liked/disliked job_ids for a user."""
    rows = sb("get", f"job_feedback?chat_id=eq.{chat_id}&select=job_id,feedback")
    liked    = {r["job_id"] for r in rows if r.get("feedback") == "like"}
    disliked = {r["job_id"] for r in rows if r.get("feedback") == "dislike"}
    return liked, disliked

def feedback_score(job, liked_ids, disliked_ids):
    """Boost jobs similar to liked ones; penalise jobs similar to disliked ones."""
    jid = job.get("_id","")
    if jid in disliked_ids:
        return -100
    if jid in liked_ids:
        return 50
    return 0

def difficulty_score(job):
    if job.get("hot"):
        return "🟢 Hot — apply today"
    source = (job.get("source","") or "").lower()
    title  = (job.get("title","")  or "").lower()
    niche  = any(k in title for k in ["moderator","ambassador","kol","discord","telegram mod",
                                       "community","web3"])
    big_co = any(s in source for s in ["greenhouse","lever","ashby"])
    if big_co and not niche:
        return "🔴 Competitive"
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
    desc    = sanitize(job.get("desc","") or job.get("description",""), max_len=120)

    lines = [f"💼 {hot}<b>{title}</b>"]
    if company:
        lines.append(f"🏢 {company}")
    lines.append(f"📍 {loc}" if loc and loc.lower() not in ("remote","") else "📍 Remote")
    if job.get("salary"):
        lines.append(f"💰 {sanitize(job['salary'])}")
    if job.get("visa_status") == "confirmed" or job.get("visa"):
        lines.append("🛂 <b>Employer visa/work-permit support confirmed</b>")
    elif job.get("overseas_candidates"):
        lines.append("🌍 Overseas applicants accepted")
    if desc:
        lines.append(f"<i>{desc}…</i>")
    lines.append(f"📊 {difficulty_score(job)}")
    if url:
        lines.append(f'🔗 <a href="{url}">Apply Now</a>  •  📌 {source}')
    if show_divider:
        lines.append("\n─────────────────")
    return "\n".join(lines)

FIND_MORE_BTN = [[{"text": "🔍 Find More Jobs", "callback_data": "find_jobs"}]]
APPLY_QUEUE_BTN = [
    [{"text": "🤖 Review Application Queue", "callback_data": "applications"}],
    [{"text": "🔍 Find More Jobs", "callback_data": "find_jobs"}],
]

def queue_applications(chat_id, jobs):
    from api.apply_agent import adapter_for, job_snapshot
    rows = []
    now = datetime.now(timezone.utc).isoformat()
    for job in jobs:
        job_id = str(job.get("_id") or job.get("job_id") or "")
        if not job_id:
            continue
        rows.append({
            "chat_id": chat_id,
            "job_id": job_id,
            "status": "queued",
            "adapter": adapter_for(job.get("url")),
            "apply_method": "review_then_open",
            "job_snapshot": job_snapshot(job),
            "updated_at": now,
        })
    if rows:
        sb("post", "applications", rows, prefer="resolution=ignore-duplicates")
    return len(rows)

def send_jobs_grouped(chat_id, jobs, batch_size=3):
    """Send jobs in groups of 3. Rate-limit sleep is minimal — Telegram allows 30 msg/s."""
    for i in range(0, len(jobs), batch_size):
        group = jobs[i:i+batch_size]
        parts = [format_job_compact(j, show_divider=idx < len(group)-1)
                 for idx, j in enumerate(group)]
        send(chat_id, "\n".join(parts))
        time.sleep(0.05)   # 50ms is enough; 500ms was causing Vercel timeouts

def run():
    logger.info("=== Scan started ===")
    from api.apply_agent import auto_apply_allowed
    from api.jobs import feedback_affinity, get_all_jobs, matches_user, score

    logger.info("Fetching active users...")
    users = sb("get", "users?active=eq.true&setup_complete=eq.true")
    logger.info(f"Active users to process: {len(users)}")
    review_profiles = sb(
        "get",
        "candidate_profiles?auto_apply_mode=eq.review&setup_step=eq.ready&select=chat_id",
    )
    users_by_chat = {user["chat_id"]: user for user in users}
    review_chat_ids = {
        row["chat_id"]
        for row in review_profiles
        if row["chat_id"] in users_by_chat
        and auto_apply_allowed(
            username=users_by_chat[row["chat_id"]].get("username", ""),
            chat_id=row["chat_id"],
        )
    }

    logger.info("Fetching all jobs from sources...")
    all_jobs = get_all_jobs(users=users)
    store_jobs(all_jobs)

    sent_count    = 0
    skipped_count = 0

    for user in users:
        chat_id  = user["chat_id"]
        keywords = user.get("keywords","")

        # Skip if alerted within last MIN_HOURS_BETWEEN_ALERTS hours
        # (prevents double-send on Vercel cron retries while allowing 3×/day)
        if was_alerted_recently(user):
            logger.info(f"User {chat_id}: skipped — alerted within last {MIN_HOURS_BETWEEN_ALERTS}h")
            skipped_count += 1
            continue

        # Load feedback to boost/suppress jobs
        liked_ids, disliked_ids = get_user_feedback(chat_id)
        liked_jobs = [j for j in all_jobs if j.get("_id") in liked_ids]

        matched = [j for j in all_jobs
                   if matches_user(j, user)
                   and not was_sent(chat_id, j["_id"])
                   and j["_id"] not in disliked_ids]   # hard-filter disliked jobs
        matched.sort(key=lambda j: (
            -feedback_score(j, liked_ids, disliked_ids),
            -feedback_affinity(j, liked_jobs),
            -score(j["title"], keywords),
            not j.get("hot",False)
        ))
        batch = matched[:9]

        logger.info(f"User {chat_id}: {len(matched)} matches, sending {len(batch)}")

        if not batch:
            last_alert = user.get("last_alert_date")
            if last_alert:
                try:
                    days_since = (date.today() - date.fromisoformat(str(last_alert)[:10])).days
                    if days_since >= 3:
                        send(chat_id,
                            f"👋 <b>Still job hunting?</b>\n\n"
                            f"No new matches in {days_since} days. "
                            f"Try broadening your keywords or changing your seniority level.\n\n"
                            f"We scan 1,200+ jobs daily — small tweaks make a big difference.",
                            [[{"text": "🔑 Update Keywords",    "callback_data": "add_keywords"},
                              {"text": "⚙️ Change Preferences", "callback_data": "setup_start"}]])
                except Exception as e:
                    logger.error(f"Re-engagement for {chat_id}: {e}")
            else:
                send(chat_id,
                    "📭 <b>No new jobs today.</b>\n\n"
                    "All matching listings have been sent. Fresh jobs arrive tomorrow.",
                    FIND_MORE_BTN)
            skipped_count += 1
            continue

        streak    = update_streak(user)
        hot_count = sum(1 for j in batch if j.get("hot"))
        sources   = list({j["source"] for j in batch})
        top_job   = batch[0]

        header = f"🌅 <b>{len(batch)} new jobs matched your profile</b>"
        if hot_count:
            header += f" · ⚡ {hot_count} posted today"
        if streak > 1:
            header += f"\n🔥 Day {streak} streak — keep it up!"
        header += f"\n📡 {', '.join(sources[:4])}"
        header += f"\n\n🏆 <b>Top match:</b> {sanitize(top_job.get('title',''))} at {sanitize(top_job.get('company',''))}"
        send(chat_id, header)

        send_jobs_grouped(chat_id, batch)

        for job in batch:
            mark_sent(chat_id, job["_id"])

        queued_count = (
            queue_applications(chat_id, batch) if chat_id in review_chat_ids else 0
        )
        queue_note = (
            f"\n🤖 {queued_count} jobs added to your application review queue."
            if queued_count else ""
        )
        send(chat_id,
            "✅ That's today's batch.\n"
            "💡 Tip: tap 👍 on jobs you like — we'll refine your matches."
            + queue_note,
            APPLY_QUEUE_BTN if queued_count else FIND_MORE_BTN)

        sent_count += 1
        time.sleep(0.1)   # 100ms between users — enough to stay under Telegram broadcast limits

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
                     f"👁 <b>Watchlist Alert!</b> {len(watched)} new job(s) from companies you're watching:")
                send_jobs_grouped(watcher_chat_id, watched[:6])
                for job in watched[:6]:
                    mark_sent(watcher_chat_id, job["_id"])

    logger.info(f"=== Scan complete. Alerted: {sent_count}, Skipped: {skipped_count} ===")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not CRON_SECRET:
            logger.error("CRON_SECRET is required")
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b"Cron secret is not configured")
            return
        if self.headers.get("Authorization") != f"Bearer {CRON_SECRET}":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            return
        try:
            run()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Scan complete")
        except Exception as e:
            logger.error(f"Scan handler: {e}", exc=e)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Scan failed")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    run()
