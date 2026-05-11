"""
Remote Radar — Telegram Webhook
Fixes applied:
  #1  Structured logging — no more silent failures
  #3  UX: jobs sent as individual cards with action buttons
  #4  Rate limiting hardened — FIND_COOLDOWN enforced per user
  #5  Referral anti-abuse: verify referrer exists + is active user
  #7  All messages rewritten — shorter, warmer, more human
  #8  Better zero-results message with actionable tips
  #9  HTML injection: all external data double-sanitised before Telegram
  #10 Analytics stub: key events tracked to Supabase analytics table
  #11 Unsave button + "I got this job!" button in /saved
  #12 Description snippet shown in job cards
  #14 Full account delete with confirmation (GDPR-safe)
  #15 Engagement loop: streak shown, daily tip on /find
  #17 /unwatch command to remove watchlist entries
  #18 Pagination: /find returns 5 jobs + "Load more" button
  #SH /search command for one-off search without changing profile
  #FB Feedback loop: likes/dislikes influence feed
  #21 FSM bug fix: handle_start no longer resets awaiting_role
  #22 step1_role now uses send() so prompt always arrives
  #23 FIX: all awaiting_role=True writes now use PATCH (update_user)
       so the flag is actually saved — was silently failing with sb_post
       when Supabase has no UNIQUE constraint on chat_id
"""
import os, json, time, requests, re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler
from api import logger

BOT_TOKEN    = os.environ.get("JOB_BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
TG_API       = f"https://api.telegram.org/bot{BOT_TOKEN}"
BOT_USERNAME = os.environ.get("BOT_USERNAME", "RemoteDailyJobBot")
FIND_COOLDOWN = 60   # seconds between /find calls

WELCOME = """👋 <b>Welcome to Remote Radar!</b>

Get fresh remote job alerts on Telegram — free, forever, worldwide.

🌍 12 global sources, scanned daily
🎯 Fully personalised to your role
⚡ Hot jobs flagged within 24h
💰 Salary & funding info included

Takes 60 seconds to set up 👇

<i>Built by <a href="https://t.me/Harsimarhs">@Harsimarhs</a> — questions always welcome</i>"""

# ── Sanitization ──────────────────────────────────────────────────────────────

def sanitize(text, max_len=200):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", str(text))
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.strip()[:max_len]

def sanitize_url(url):
    if not url:
        return ""
    try:
        parsed = urlparse(str(url))
        if parsed.scheme not in ("http", "https"):
            return ""
        return str(url).replace("'", "%27").replace('"', "%22").replace("<", "%3C").replace(">", "%3E")
    except Exception:
        return ""

# ── Supabase ──────────────────────────────────────────────────────────────────

def _hdr(extra=None):
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
         "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h

def sb_get(path):
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=_hdr(), timeout=10)
        if r.status_code == 200:
            return r.json()
        logger.sb_error("get", path, r.status_code, r.text)
        return []
    except Exception as e:
        logger.error(f"sb_get {path}: {e}")
        return []

def sb_post(path, body, prefer="resolution=merge-duplicates"):
    try:
        r = requests.post(f"{SUPABASE_URL}/rest/v1/{path}",
                          headers=_hdr({"Prefer": prefer}), json=body, timeout=10)
        if r.status_code not in (200, 201):
            logger.sb_error("post", path, r.status_code, r.text)
    except Exception as e:
        logger.error(f"sb_post {path}: {e}")

def sb_patch(path, body):
    try:
        r = requests.patch(f"{SUPABASE_URL}/rest/v1/{path}",
                           headers=_hdr(), json=body, timeout=10)
        if r.status_code not in (200, 204):
            logger.sb_error("patch", path, r.status_code, r.text)
    except Exception as e:
        logger.error(f"sb_patch {path}: {e}")

def sb_delete(path):
    try:
        r = requests.delete(f"{SUPABASE_URL}/rest/v1/{path}", headers=_hdr(), timeout=10)
        if r.status_code not in (200, 204):
            logger.sb_error("delete", path, r.status_code, r.text)
    except Exception as e:
        logger.error(f"sb_delete {path}: {e}")

# ── Analytics ─────────────────────────────────────────────────────────────────

def track(chat_id, event, meta=None):
    try:
        sb_post("analytics", {
            "chat_id": chat_id,
            "event":   event,
            "meta":    json.dumps(meta or {}),
            "ts":      datetime.now(timezone.utc).isoformat(),
        }, prefer="return=minimal")
    except Exception:
        pass

# ── User helpers ──────────────────────────────────────────────────────────────

def get_user(chat_id):
    r = sb_get(f"users?chat_id=eq.{chat_id}&select=*")
    return r[0] if r else {}

def set_user(chat_id, data):
    data["chat_id"] = chat_id
    sb_post("users", data)

def update_user(chat_id, data):
    sb_patch(f"users?chat_id=eq.{chat_id}", data)

def was_sent(chat_id, job_id):
    r = sb_get(f"sent_jobs?chat_id=eq.{chat_id}&job_id=eq.{job_id}&select=id&limit=1")
    return bool(r)

def mark_sent(chat_id, job_id):
    sb_post("sent_jobs", {"chat_id": chat_id, "job_id": str(job_id)},
            prefer="resolution=ignore-duplicates")

def get_cached_jobs():
    return sb_get("jobs?select=*&order=scraped_at.desc&limit=2000")

def inc_referrals(chat_id):
    user = get_user(chat_id)
    update_user(chat_id, {"referrals": (user.get("referrals") or 0) + 1})

def check_rate_limit(chat_id):
    user = get_user(chat_id)
    last = user.get("last_find_at")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
        return elapsed >= FIND_COOLDOWN
    except Exception:
        return True

def save_job(chat_id, job):
    sb_post("saved_jobs", {
        "chat_id":   chat_id,
        "job_id":    job.get("job_id", ""),
        "job_title": sanitize(job.get("title", "")),
        "company":   sanitize(job.get("company", "")),
        "url":       sanitize_url(job.get("url", "")),
        "source":    sanitize(job.get("source", "")),
    }, prefer="resolution=ignore-duplicates")

def save_feedback(chat_id, job_id, feedback):
    sb_post("job_feedback", {"chat_id": chat_id, "job_id": job_id, "feedback": feedback},
            prefer="resolution=merge-duplicates")

def get_user_feedback(chat_id):
    rows = sb_get(f"job_feedback?chat_id=eq.{chat_id}&select=job_id,feedback")
    liked    = {r["job_id"] for r in rows if r.get("feedback") == "like"}
    disliked = {r["job_id"] for r in rows if r.get("feedback") == "dislike"}
    return liked, disliked

# ── Telegram helpers ──────────────────────────────────────────────────────────

def send(chat_id, text, keyboard=None, retries=3):
    text = str(text)[:4096]
    payload = {"chat_id": chat_id, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    for attempt in range(retries):
        try:
            r = requests.post(f"{TG_API}/sendMessage", json=payload, timeout=10)
            if r.status_code == 200:
                return True
            if r.status_code == 429:
                wait = r.json().get("parameters", {}).get("retry_after", 5)
                logger.warn(f"TG rate limit for {chat_id} — waiting {wait}s")
                time.sleep(min(wait, 30))
                continue
            logger.tg_send(chat_id, r.status_code, text[:80])
            return False
        except Exception as e:
            logger.error(f"send to {chat_id} attempt {attempt+1}: {e}")
            if attempt < retries - 1:
                time.sleep(1)
    return False

def edit(chat_id, msg_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "message_id": msg_id,
                "text": str(text)[:4096], "parse_mode": "HTML",
                "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    try:
        r = requests.post(f"{TG_API}/editMessageText", json=payload, timeout=10)
        if r.status_code not in (200, 400):
            logger.error(f"edit message {chat_id}/{msg_id}: {r.status_code}")
    except Exception as e:
        logger.error(f"edit {chat_id}/{msg_id}: {e}")

def answer(cb_id, text=""):
    try:
        r = requests.post(f"{TG_API}/answerCallbackQuery",
                          json={"callback_query_id": cb_id, "text": text[:200]}, timeout=5)
        if r.status_code != 200:
            logger.warn(f"answerCallbackQuery failed: {r.status_code}")
    except Exception as e:
        logger.error(f"answerCallbackQuery: {e}")

# ── Job formatting ────────────────────────────────────────────────────────────

def difficulty_score(job):
    if job.get("hot"):
        return "🟢 Hot — apply today"
    source = (job.get("source", "") or "").lower()
    title  = (job.get("title", "")  or "").lower()
    niche  = any(k in title for k in ["moderator", "ambassador", "kol", "discord mod",
                                       "telegram mod", "community", "web3", "crypto", "dao"])
    big_co = any(s in source for s in ["greenhouse", "lever", "ashby"])
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
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%-d %b %Y")
    except Exception:
        try:
            return str(date_val)[:10]
        except Exception:
            return ""

def format_job_card(job, show_actions=True):
    hot     = "🔥 " if job.get("hot") else ""
    title   = sanitize(job.get("title", ""))
    company = sanitize(job.get("company", ""))
    loc     = sanitize(job.get("location", ""))
    url     = sanitize_url(job.get("url", ""))
    source  = sanitize(job.get("source", ""))
    desc    = sanitize(job.get("desc","") or job.get("description",""), max_len=120)
    job_id  = job.get("job_id", "") or job.get("_id", "")

    lines = [f"💼 {hot}<b>{title}</b>"]
    if company:
        lines.append(f"🏢 {company}")
    lines.append(f"📍 {loc}" if loc and loc.lower() not in ("remote", "") else "📍 Remote")
    if job.get("salary"):
        lines.append(f"💰 {sanitize(job['salary'])}")
    if job.get("funding"):
        lines.append(f"💸 Funded: {sanitize(job['funding'])}")
    if job.get("visa"):
        lines.append("✈️ Visa sponsorship available")
    if desc:
        lines.append(f"<i>{desc}…</i>")
    lines.append(f"📊 {difficulty_score(job)}")
    d = fmt_date(job.get("date") or job.get("date_posted", ""))
    if d:
        lines.append(f"📅 {d}")
    if url:
        lines.append(f'🔗 <a href="{url}">Apply Now</a>  •  📌 {source}')

    text    = "\n".join(lines)
    buttons = None
    if show_actions and job_id:
        buttons = [
            [{"text": "👍 Good match",  "callback_data": f"like_{job_id}"},
             {"text": "👎 Not relevant","callback_data": f"dislike_{job_id}"}],
            [{"text": "🔖 Save",        "callback_data": f"save_{job_id}"},
             {"text": "📤 Share",       "callback_data": f"share_{job_id}"}],
        ]
    return text, buttons

# ── Keyboards ─────────────────────────────────────────────────────────────────

def kb_main():
    return [[{"text": "⚙️ Set Up Alerts", "callback_data": "setup_start"}],
            [{"text": "📋 My Preferences", "callback_data": "status"},
             {"text": "⏹ Pause",           "callback_data": "stop"}]]

def kb_seniority():
    return [
        [{"text": "🌱 Entry Level",    "callback_data": "sen_entry"},
         {"text": "📈 Mid Level",      "callback_data": "sen_mid"}],
        [{"text": "⭐ Senior",         "callback_data": "sen_senior"},
         {"text": "👥 Manager / Lead", "callback_data": "sen_manager"}],
        [{"text": "🏆 Director / VP",  "callback_data": "sen_director"},
         {"text": "👑 C-Suite",        "callback_data": "sen_executive"}],
        [{"text": "🌍 All Levels",     "callback_data": "sen_all"}],
    ]

def kb_location():
    return [
        [{"text": "🌍 Remote Only",     "callback_data": "loc_remote"}],
        [{"text": "🇺🇸 USA",           "callback_data": "loc_usa"},
         {"text": "🇬🇧 UK",           "callback_data": "loc_uk"}],
        [{"text": "🇮🇳 India",         "callback_data": "loc_india"},
         {"text": "🇳🇬 Nigeria",       "callback_data": "loc_nigeria"}],
        [{"text": "🇯🇵 Japan",         "callback_data": "loc_japan"},
         {"text": "🇨🇳 China",         "callback_data": "loc_china"}],
        [{"text": "🌏 SE Asia",         "callback_data": "loc_sea"},
         {"text": "🕌 Middle East",     "callback_data": "loc_me"}],
        [{"text": "🇪🇺 Europe",        "callback_data": "loc_europe"}],
        [{"text": "🌐 Worldwide",        "callback_data": "loc_worldwide"}],
    ]

def kb_company_type():
    return [
        [{"text": "🚀 Startups & Scale-ups",  "callback_data": "ctype_startup"}],
        [{"text": "🏢 Established Companies", "callback_data": "ctype_established"}],
        [{"text": "🌍 Both / Any",            "callback_data": "ctype_any"}],
    ]

def kb_after_jobs():
    return [
        [{"text": "🔍 Find More", "callback_data": "find_jobs"}],
        [{"text": "🔖 Saved",     "callback_data": "show_saved"},
         {"text": "📋 Profile",   "callback_data": "status"}],
    ]

SEN_LABELS = {
    "entry": "🌱 Entry Level", "mid": "📈 Mid Level", "senior": "⭐ Senior",
    "manager": "👥 Manager / Lead", "director": "🏆 Director / VP",
    "executive": "👑 C-Suite", "all": "🌍 All Levels",
}
LOC_LABELS = {
    "remote":    "🌍 Remote Only",  "usa": "🇺🇸 USA", "uk": "🇬🇧 UK",
    "india":     "🇮🇳 India",       "nigeria": "🇳🇬 Nigeria", "japan": "🇯🇵 Japan",
    "china":     "🇨🇳 China",       "sea": "🌏 SE Asia",       "me": "🕌 Middle East",
    "europe":    "🇪🇺 Europe",      "worldwide": "🌐 Worldwide",
}
CTYPE_LABELS = {
    "startup": "🚀 Startups", "established": "🏢 Established", "any": "🌍 Any",
}
LOC_MAP = {
    "remote":    ("Remote",         True),
    "usa":       ("USA",            False),
    "uk":        ("UK",             False),
    "india":     ("India",          False),
    "nigeria":   ("Nigeria",        False),
    "japan":     ("Japan",          False),
    "china":     ("China",          False),
    "sea":       ("Southeast Asia", False),
    "me":        ("Middle East",    False),
    "europe":    ("Europe",         False),
    "worldwide": ("Worldwide",      False),
}

# ── Job matching ──────────────────────────────────────────────────────────────

def job_matches_user(job, user):
    try:
        from api.jobs import is_title_relevant, matches_location, matches_seniority
        title = sanitize(job.get("title", ""))
        if not is_title_relevant(title, user.get("keywords", ""), user.get("category", "all")):
            return False
        if not matches_location(job.get("location", "Remote"), user.get("location", "Remote"),
                                user.get("remote_only", True)):
            return False
        if not matches_seniority(title, user.get("seniority", "all")):
            return False
        ctype = user.get("company_type", "any")
        if ctype == "startup" and job.get("company_type", "") not in ("startup",""):
            return False
        if ctype == "established" and job.get("company_type", "") == "startup":
            return False
        return True
    except Exception as e:
        logger.error(f"job_matches_user: {e}")
        return False

def send_jobs_from_cache(chat_id, user, page=0, keyword_override=None):
    if not check_rate_limit(chat_id):
        send(chat_id, f"⏳ Please wait {FIND_COOLDOWN}s between searches.")
        return

    send(chat_id, "🔍 Searching for matching jobs...")
    update_user(chat_id, {
        "last_find_at":   datetime.now(timezone.utc).isoformat(),
        "last_active_at": datetime.now(timezone.utc).isoformat(),
    })
    track(chat_id, "find_jobs", {"page": page})

    cached = get_cached_jobs()
    if not cached:
        send(chat_id, "No jobs cached yet — the daily scan runs at 9am UTC.", kb_main())
        return

    from api.jobs import score
    keywords = keyword_override or user.get("keywords", "")

    liked_ids, disliked_ids = get_user_feedback(chat_id)

    if keyword_override:
        matched = [j for j in cached
                   if keyword_override.lower() in (j.get("title","") or "").lower()
                   and j.get("job_id","") not in disliked_ids]
    else:
        matched = [j for j in cached
                   if job_matches_user(j, user)
                   and not was_sent(chat_id, j["job_id"])
                   and j.get("job_id","") not in disliked_ids]

    matched.sort(key=lambda j: (
        -(50 if j.get("job_id","") in liked_ids else 0),
        -score(j.get("title",""), keywords),
        not j.get("hot", False)
    ))

    per_page = 5
    start    = page * per_page
    batch    = matched[start:start + per_page]
    has_more = len(matched) > start + per_page

    if not batch:
        tips = (
            "📭 <b>No new matches found.</b>\n\n"
            "A few things to try:\n"
            "• Broaden your keywords (e.g. <code>marketing</code> instead of <code>web3 marketing manager</code>)\n"
            "• Switch seniority to <b>All Levels</b>\n"
            "• Set location to <b>Worldwide</b>\n\n"
            "Fresh jobs arrive every few hours."
        )
        send(chat_id, tips,
             [[{"text": "🔑 Update Keywords",    "callback_data": "add_keywords"},
               {"text": "⚙️ Change Preferences", "callback_data": "setup_start"}]])
        return

    hot_count = sum(1 for j in batch if j.get("hot"))
    sources   = list({j["source"] for j in batch})
    header    = f"🔍 <b>{len(batch)} jobs for you</b>"
    if hot_count:
        header += f" · ⚡ {hot_count} posted today"
    header += f"\n📡 {', '.join(sources[:4])}"
    send(chat_id, header)

    for job in batch:
        text, buttons = format_job_card(job, show_actions=True)
        send(chat_id, text, buttons)
        if not keyword_override:
            mark_sent(chat_id, job["job_id"])
        time.sleep(0.1)

    footer_kb = kb_after_jobs()
    if has_more:
        footer_kb = [[{"text": f"➡️ Load {min(5, len(matched) - start - per_page)} more",
                       "callback_data": f"find_page_{page+1}"}]] + footer_kb

    send(chat_id, "✅ Tap 👍 on good matches — it trains your feed.", footer_kb)

# ── Onboarding FSM ────────────────────────────────────────────────────────────

SETUP_STEPS = ["awaiting_role", "awaiting_seniority", "awaiting_location", "awaiting_ctype"]

def get_current_step(user):
    for step in SETUP_STEPS:
        if user.get(step):
            return step
    return None

def _reset_to_step1(chat_id):
    """
    FIX #23: Always use update_user (PATCH) to set awaiting_role=True.
    sb_post (upsert) silently fails when Supabase has no UNIQUE constraint
    on chat_id — it inserts a second row and get_user still returns the
    original row with awaiting_role=False.
    """
    update_user(chat_id, {
        "awaiting_role":      True,
        "awaiting_seniority": False,
        "awaiting_location":  False,
        "awaiting_ctype":     False,
        "awaiting_keywords":  False,
    })

# ── Handlers ──────────────────────────────────────────────────────────────────

def handle_start(chat_id, username, ref_code=None):
    existing = get_user(chat_id)
    is_new   = not existing

    if existing:
        update_user(chat_id, {"username": username or ""})
        step = get_current_step(existing)
        if step == "awaiting_role":
            send(chat_id,
                 "⚙️ <b>Step 1 of 4 — Your Role</b>\n\n"
                 "What job role are you looking for?\n\n"
                 "<b>Examples:</b>\n"
                 "• <code>Community Manager</code>\n"
                 "• <code>Web3 Marketing Manager</code>\n"
                 "• <code>Discord Moderator</code>\n"
                 "• <code>Software Engineer</code>\n\n"
                 "Type your role and send 👇",
                 [[{"text": "❌ Cancel", "callback_data": "status"}]])
            return
        elif step in ("awaiting_seniority", "awaiting_location", "awaiting_ctype"):
            # FIX #23: use update_user (PATCH) not sb_post (upsert)
            _reset_to_step1(chat_id)
            send(chat_id,
                 "👋 Let's pick up where you left off.\n\n"
                 "<b>Step 1 of 4 — Your Role</b>\n\nType your role and send 👇",
                 [[{"text": "❌ Cancel", "callback_data": "status"}]])
            return
    else:
        set_user(chat_id, {
            "username":           username or "",
            "active":             False,
            "setup_complete":     False,
            "category":           "all",
            "seniority":          "all",
            "keywords":           "",
            "location":           "Worldwide",
            "location_key":       "worldwide",
            "remote_only":        False,
            "company_type":       "any",
            "awaiting_keywords":  False,
            "awaiting_role":      False,
            "awaiting_seniority": False,
            "awaiting_location":  False,
            "awaiting_ctype":     False,
            "streak":             0,
            "referrals":          0,
            "referred_by":        None,
        })

    if is_new and ref_code and ref_code.startswith("ref_"):
        try:
            referrer_id = int(ref_code.replace("ref_", ""))
            if referrer_id != chat_id:
                referrer = get_user(referrer_id)
                if referrer and referrer.get("setup_complete"):
                    update_user(chat_id, {"referred_by": referrer_id})
                    inc_referrals(referrer_id)
                    track(referrer_id, "referral_credited", {"new_user": chat_id})
                    count = (referrer.get("referrals") or 0) + 1
                    send(referrer_id,
                         f"🎉 Someone joined using your link!\n\n"
                         f"👥 You've referred <b>{count}</b> {'person' if count == 1 else 'people'}.\n\n"
                         f"Keep sharing: <code>t.me/{BOT_USERNAME}?start=ref_{referrer_id}</code>")
        except (ValueError, TypeError) as e:
            logger.warn(f"Bad referral code '{ref_code}': {e}")

    track(chat_id, "start", {"is_new": is_new})
    send(chat_id, WELCOME, kb_main())

def handle_status(chat_id):
    user = get_user(chat_id)
    if not user or not user.get("setup_complete"):
        send(chat_id, "You haven't set up alerts yet.", kb_main())
        return
    kws       = user.get("keywords", "") or "—"
    status    = "✅ Active" if user.get("active") else "⏸ Paused"
    referrals = user.get("referrals", 0) or 0
    streak    = user.get("streak", 0) or 0
    invite    = f"t.me/{BOT_USERNAME}?start=ref_{chat_id}"
    send(chat_id,
         f"📋 <b>Your Profile</b>\n\n"
         f"🎯 Keywords: {sanitize(kws)}\n"
         f"🎓 Level: {SEN_LABELS.get(user.get('seniority', 'all'), 'All Levels')}\n"
         f"📍 Location: {LOC_LABELS.get(user.get('location_key', 'worldwide'), 'Worldwide')}\n"
         f"🏢 Company: {CTYPE_LABELS.get(user.get('company_type', 'any'), 'Any')}\n"
         f"📡 Alerts: {status}"
         + (f"\n🔥 {streak}-day streak!" if streak > 1 else "") +
         f"\n\n👥 Referrals: <b>{referrals}</b>\n"
         f"🔗 <code>{invite}</code>",
         [[{"text": "✏️ Edit Preferences", "callback_data": "setup_start"},
           {"text": "⏹ Pause",             "callback_data": "stop"}],
          [{"text": "🔍 Find Jobs Now",     "callback_data": "find_jobs"},
           {"text": "🔖 Saved",             "callback_data": "show_saved"}],
          [{"text": "👥 Invite Friends",    "callback_data": "invite"}]])

def handle_saved(chat_id):
    saved = sb_get(f"saved_jobs?chat_id=eq.{chat_id}&select=*&order=created_at.desc&limit=10")
    if not saved:
        send(chat_id,
             "🔖 <b>No saved jobs yet.</b>\n\nTap <b>🔖 Save</b> on any job to bookmark it here.",
             [[{"text": "🔍 Find Jobs Now", "callback_data": "find_jobs"}]])
        return
    send(chat_id, f"🔖 <b>Saved Jobs ({len(saved)})</b>")
    for j in saved:
        url     = sanitize_url(j.get("url", ""))
        title   = sanitize(j.get("job_title", ""))
        company = sanitize(j.get("company", ""))
        job_id  = j.get("job_id","")
        line    = f"💼 <b>{title}</b>\n🏢 {company}\n"
        if url:
            line += f'🔗 <a href="{url}">Apply Now</a>'
        buttons = None
        if job_id:
            buttons = [
                [{"text": "🗑 Remove",           "callback_data": f"unsave_{job_id}"},
                 {"text": "🎉 I got this job!",  "callback_data": f"gotjob_{job_id}"}],
            ]
        send(chat_id, line, buttons)
        time.sleep(0.1)

def handle_invite(chat_id):
    user      = get_user(chat_id)
    referrals = user.get("referrals", 0) or 0
    invite    = f"t.me/{BOT_USERNAME}?start=ref_{chat_id}"
    send(chat_id,
         f"👥 <b>Invite Friends</b>\n\n"
         f"Your link: <code>{invite}</code>\n\n"
         f"People invited: <b>{referrals}</b>\n\n"
         f"<i>Send this to anyone job hunting — free daily remote alerts, set up in 60 seconds.</i>")

def handle_stop(chat_id):
    update_user(chat_id, {"active": False})
    track(chat_id, "paused")
    send(chat_id, "⏸ Alerts paused.",
         [[{"text": "▶️ Resume Alerts", "callback_data": "setup_start"}]])

def handle_delete(chat_id):
    try:
        sb_delete(f"users?chat_id=eq.{chat_id}")
        sb_delete(f"sent_jobs?chat_id=eq.{chat_id}")
        sb_delete(f"watchlist?chat_id=eq.{chat_id}")
        sb_delete(f"saved_jobs?chat_id=eq.{chat_id}")
        sb_delete(f"job_feedback?chat_id=eq.{chat_id}")
        sb_delete(f"analytics?chat_id=eq.{chat_id}")
        logger.info(f"Account deleted for {chat_id}")
    except Exception as e:
        logger.error(f"Delete account {chat_id}: {e}")
    send(chat_id, "🗑 All your data has been deleted. Send /start anytime to begin again.")

def handle_watch(chat_id, text):
    company = sanitize(text.replace("/watch", "").strip(), max_len=100)
    if not company or len(company) < 2:
        send(chat_id, "Usage: <code>/watch Coinbase</code>")
        return
    sb_post("watchlist", {"chat_id": chat_id, "company": company},
            prefer="resolution=ignore-duplicates")
    send(chat_id, f"👁 Watching <b>{company}</b> — you'll be alerted when they post.")

def handle_unwatch(chat_id, text):
    company = sanitize(text.replace("/unwatch", "").strip(), max_len=100)
    if not company or len(company) < 2:
        watchlist = sb_get(f"watchlist?chat_id=eq.{chat_id}&select=company")
        if not watchlist:
            send(chat_id, "You're not watching any companies.")
            return
        names = "\n".join(f"• {w['company']}" for w in watchlist)
        send(chat_id,
             f"👁 <b>Watched companies:</b>\n{names}\n\n"
             f"To remove one: <code>/unwatch Coinbase</code>")
        return
    sb_delete(f"watchlist?chat_id=eq.{chat_id}&company=eq.{company}")
    send(chat_id, f"✅ Stopped watching <b>{company}</b>.")

def handle_keywords(chat_id, text):
    keywords = sanitize(text.replace("/keywords", "").strip().lstrip(","), max_len=300)
    if not keywords:
        update_user(chat_id, {"awaiting_keywords": True})
        send(chat_id,
             "✏️ <b>Update Keywords</b>\n\nType your keywords — comma-separated:\n\n"
             "• <code>community manager, web3</code>\n"
             "• <code>ambassador, discord mod</code>\n"
             "• <code>ux designer, figma</code>")
        return
    update_user(chat_id, {"keywords": keywords, "awaiting_keywords": False})
    send(chat_id, f"✅ Keywords updated to: <b>{keywords}</b>")
    user = get_user(chat_id)
    send_jobs_from_cache(chat_id, user)

def handle_search(chat_id, text):
    query = sanitize(text.replace("/search", "").strip(), max_len=150)
    if not query:
        update_user(chat_id, {"awaiting_search": True})
        send(chat_id,
             "🔍 <b>Quick Search</b>\n\nType a role or keyword to search right now — "
             "this won't change your saved profile:\n\n"
             "• <code>community manager</code>\n"
             "• <code>web3 growth</code>\n"
             "• <code>discord moderator</code>")
        return
    user = get_user(chat_id)
    send_jobs_from_cache(chat_id, user, keyword_override=query)

# ── Onboarding steps ──────────────────────────────────────────────────────────

def step1_role(chat_id, msg_id):
    # FIX #23: use update_user (PATCH) not sb_post (upsert)
    # sb_post without a UNIQUE constraint on chat_id inserts a second row;
    # get_user then returns the OLD row (awaiting_role still False) and
    # the role text falls through to the "Not sure what you mean" fallback.
    _reset_to_step1(chat_id)
    try:
        edit(chat_id, msg_id, "⚙️ Setting up your alerts...")
    except Exception:
        pass
    send(chat_id,
         "⚙️ <b>Step 1 of 4 — Your Role</b>\n\n"
         "What job are you looking for?\n\n"
         "<b>Examples:</b>\n"
         "• <code>Community Manager</code>\n"
         "• <code>Web3 Marketing</code>\n"
         "• <code>Discord Moderator</code>\n"
         "• <code>Software Engineer</code>\n"
         "• <code>Customer Support</code>\n\n"
         "Type and send 👇",
         [[{"text": "❌ Cancel", "callback_data": "status"}]])

def step2_seniority(chat_id, role):
    update_user(chat_id, {"awaiting_role": False, "awaiting_seniority": True})
    send(chat_id,
         f"✅ Role: <b>{sanitize(role)}</b>\n\n"
         f"⚙️ <b>Step 2 of 4 — Level</b>\n\nWhat seniority are you targeting?",
         kb_seniority())

def step3_location(chat_id, msg_id, seniority, cb_id):
    answer(cb_id, f"✅ {SEN_LABELS.get(seniority, seniority)}")
    update_user(chat_id, {"seniority": seniority, "awaiting_seniority": False,
                           "awaiting_location": True})
    edit(chat_id, msg_id,
         f"✅ Level: {SEN_LABELS.get(seniority, seniority)}\n\n"
         f"⚙️ <b>Step 3 of 4 — Location</b>\n\nWhere are you looking to work?",
         kb_location())

def step4_company_type(chat_id, msg_id, loc_key, cb_id):
    loc_name, remote_only = LOC_MAP.get(loc_key, ("Worldwide", False))
    answer(cb_id, f"✅ {LOC_LABELS.get(loc_key, loc_key)}")
    update_user(chat_id, {"location": loc_name, "location_key": loc_key,
                           "remote_only": remote_only, "awaiting_location": False,
                           "awaiting_ctype": True})
    edit(chat_id, msg_id,
         f"✅ Location: {LOC_LABELS.get(loc_key, loc_key)}\n\n"
         f"⚙️ <b>Step 4 of 4 — Company Type</b>\n\nWhat kind of company do you prefer?",
         kb_company_type())

def finish_setup(chat_id, msg_id, ctype, cb_id):
    answer(cb_id, f"✅ {CTYPE_LABELS.get(ctype, ctype)}")
    update_user(chat_id, {"company_type": ctype, "active": True, "setup_complete": True,
                           "awaiting_ctype": False})
    user   = get_user(chat_id)
    invite = f"t.me/{BOT_USERNAME}?start=ref_{chat_id}"
    track(chat_id, "setup_complete")
    send(chat_id,
         f"🎉 <b>You're all set!</b>\n\n"
         f"🎯 {sanitize(user.get('keywords', ''))}\n"
         f"🎓 {SEN_LABELS.get(user.get('seniority', 'all'), 'All Levels')}\n"
         f"📍 {LOC_LABELS.get(user.get('location_key', 'worldwide'), 'Worldwide')}\n"
         f"🏢 {CTYPE_LABELS.get(ctype, 'Any')}\n\n"
         f"Alerts go out 3× daily. Find jobs right now 👇\n\n"
         f"👥 Share: <code>{invite}</code>",
         [[{"text": "🔍 Find Jobs Now",  "callback_data": "find_jobs"},
           {"text": "👥 Invite",         "callback_data": "invite"}]])

# ── Main update processor ─────────────────────────────────────────────────────

def process_update(update):
    try:
        if "message" in update:
            msg      = update["message"]
            chat_id  = msg["chat"]["id"]
            username = msg.get("from", {}).get("username", "")
            text     = msg.get("text", "") or ""

            if text and not text.startswith("/"):
                # FIX #23: always re-fetch user from DB here — never use
                # a cached/stale copy — so we see the latest awaiting_* flags.
                user = get_user(chat_id)
                logger.info(f"Text from {chat_id}: '{text[:40]}' | "
                            f"awaiting_role={user.get('awaiting_role')} "
                            f"awaiting_keywords={user.get('awaiting_keywords')} "
                            f"awaiting_search={user.get('awaiting_search')}")

                if user.get("awaiting_role"):
                    role = sanitize(text.strip(), max_len=150)
                    if not role:
                        send(chat_id, "Please type a role name.")
                        return
                    update_user(chat_id, {
                        "keywords":      role,
                        "category":      "all",
                        "awaiting_role": False,
                    })
                    step2_seniority(chat_id, role)
                    return

                if user.get("awaiting_keywords"):
                    kw = sanitize(text.strip(), max_len=300)
                    update_user(chat_id, {
                        "keywords":          kw,
                        "awaiting_keywords": False,
                    })
                    send(chat_id, f"✅ Keywords updated: <b>{kw}</b>")
                    send_jobs_from_cache(chat_id, user)
                    return

                if user.get("awaiting_search"):
                    query = sanitize(text.strip(), max_len=150)
                    update_user(chat_id, {"awaiting_search": False})
                    send_jobs_from_cache(chat_id, user, keyword_override=query)
                    return

                send(chat_id, "Not sure what you mean — use the buttons or try /help.", kb_main())
                return

            if text.startswith("/start"):
                parts    = text.split(" ", 1)
                ref_code = parts[1].strip() if len(parts) > 1 else None
                handle_start(chat_id, username, ref_code)
            elif text.startswith("/keywords"):
                handle_keywords(chat_id, text)
            elif text.startswith("/search"):
                handle_search(chat_id, text)
            elif text.startswith("/find"):
                user = get_user(chat_id)
                if user.get("setup_complete"):
                    send_jobs_from_cache(chat_id, user)
                else:
                    send(chat_id, "Please set up your preferences first.", kb_main())
            elif text.startswith("/saved"):
                handle_saved(chat_id)
            elif text.startswith("/unwatch"):
                handle_unwatch(chat_id, text)
            elif text.startswith("/watch "):
                handle_watch(chat_id, text)
            elif text.startswith("/invite") or text.startswith("/refer"):
                handle_invite(chat_id)
            elif text.startswith("/stop"):
                handle_stop(chat_id)
            elif text.startswith("/status"):
                handle_status(chat_id)
            elif text.startswith("/setup"):
                user = get_user(chat_id)
                if not user:
                    set_user(chat_id, {"username": username or "", "active": False,
                                       "setup_complete": False})
                step = get_current_step(user) if user else None
                if step or not (user or {}).get("setup_complete"):
                    # FIX #23: use update_user (PATCH) not sb_post (upsert)
                    _reset_to_step1(chat_id)
                    send(chat_id,
                         "⚙️ <b>Step 1 of 4 — Your Role</b>\n\nType your role and send 👇",
                         [[{"text": "❌ Cancel", "callback_data": "status"}]])
                else:
                    send(chat_id, "What would you like to change?",
                         [[{"text": "✏️ Change Role / Keywords", "callback_data": "add_keywords"}],
                          [{"text": "🔄 Redo Full Setup",         "callback_data": "setup_start"}]])
            elif text.startswith("/delete"):
                send(chat_id,
                     "⚠️ This will permanently delete all your data. Are you sure?",
                     [[{"text": "🗑 Yes, delete",  "callback_data": "confirm_delete"},
                       {"text": "❌ Cancel",        "callback_data": "status"}]])
            elif text.startswith("/help"):
                send(chat_id,
                     "📖 <b>Commands</b>\n\n"
                     "/find — Find jobs now\n"
                     "/search <i>keyword</i> — Quick search without changing profile\n"
                     "/keywords — Update keywords\n"
                     "/saved — Saved jobs\n"
                     "/watch <i>Company</i> — Get notified when a company posts\n"
                     "/unwatch — Manage watchlist\n"
                     "/status — View your profile\n"
                     "/setup — Update preferences\n"
                     "/invite — Your referral link\n"
                     "/stop — Pause alerts\n"
                     "/delete — Delete account")

        elif "callback_query" in update:
            cb       = update["callback_query"]
            chat_id  = cb["from"]["id"]
            username = cb["from"].get("username", "")
            msg_id   = cb["message"]["message_id"]
            data     = cb.get("data", "")
            cb_id    = cb["id"]

            if not get_user(chat_id):
                set_user(chat_id, {"username": username, "active": False,
                                   "setup_complete": False})

            if data.startswith("like_"):
                job_id = data.replace("like_", "")
                save_feedback(chat_id, job_id, "like")
                track(chat_id, "job_like", {"job_id": job_id})
                answer(cb_id, "👍 Got it — we'll show more like this.")

            elif data.startswith("dislike_"):
                job_id = data.replace("dislike_", "")
                save_feedback(chat_id, job_id, "dislike")
                track(chat_id, "job_dislike", {"job_id": job_id})
                answer(cb_id, "👎 Noted — won't show you these.")

            elif data.startswith("save_"):
                job_id = data.replace("save_", "")
                cached = sb_get(f"jobs?job_id=eq.{job_id}&select=*&limit=1")
                if cached:
                    save_job(chat_id, cached[0])
                    track(chat_id, "job_saved", {"job_id": job_id})
                    answer(cb_id, "🔖 Saved! View with /saved")
                else:
                    answer(cb_id, "Could not save — job not found.")

            elif data.startswith("unsave_"):
                job_id = data.replace("unsave_", "")
                sb_delete(f"saved_jobs?chat_id=eq.{chat_id}&job_id=eq.{job_id}")
                track(chat_id, "job_unsaved", {"job_id": job_id})
                answer(cb_id, "🗑 Removed from saved.")

            elif data.startswith("gotjob_"):
                job_id = data.replace("gotjob_", "")
                track(chat_id, "got_job", {"job_id": job_id})
                answer(cb_id, "🎉 Congratulations!")
                send(chat_id,
                     "🎉 <b>Congratulations on landing the job!</b>\n\n"
                     "Share Remote Radar with someone who's still searching 👇",
                     [[{"text": "👥 Share My Invite Link", "callback_data": "invite"}]])

            elif data.startswith("share_"):
                job_id = data.replace("share_", "")
                cached = sb_get(f"jobs?job_id=eq.{job_id}&select=*&limit=1")
                answer(cb_id)
                if cached:
                    j      = cached[0]
                    invite = f"t.me/{BOT_USERNAME}?start=ref_{chat_id}"
                    url    = sanitize_url(j.get("url", ""))
                    title  = sanitize(j.get("title", ""))
                    company = sanitize(j.get("company", ""))
                    send(chat_id,
                         f"📤 <b>Share this job:</b>\n\n"
                         f"💼 {title} @ {company}\n"
                         f"🔗 {url}\n\n"
                         f"Get daily remote alerts free: {invite}")

            elif data.startswith("find_page_"):
                try:
                    page = int(data.replace("find_page_", ""))
                    answer(cb_id, f"Loading more...")
                    user = get_user(chat_id)
                    send_jobs_from_cache(chat_id, user, page=page)
                except (ValueError, TypeError):
                    answer(cb_id, "Error loading more jobs.")

            elif data == "setup_start":
                answer(cb_id)
                step1_role(chat_id, msg_id)

            elif data == "find_jobs":
                answer(cb_id, "Searching...")
                user = get_user(chat_id)
                send_jobs_from_cache(chat_id, user)
            elif data == "show_saved":
                answer(cb_id)
                handle_saved(chat_id)
            elif data == "invite":
                answer(cb_id)
                handle_invite(chat_id)
            elif data == "add_keywords":
                answer(cb_id)
                update_user(chat_id, {"awaiting_keywords": True})
                send(chat_id, "✏️ Type your new keywords and send:")
            elif data == "status":
                answer(cb_id)
                handle_status(chat_id)
            elif data == "stop":
                answer(cb_id)
                handle_stop(chat_id)
            elif data == "confirm_delete":
                answer(cb_id)
                handle_delete(chat_id)
            elif data.startswith("sen_"):
                step3_location(chat_id, msg_id, data.replace("sen_", ""), cb_id)
            elif data.startswith("loc_"):
                step4_company_type(chat_id, msg_id, data.replace("loc_", ""), cb_id)
            elif data.startswith("ctype_"):
                finish_setup(chat_id, msg_id, data.replace("ctype_", ""), cb_id)

    except Exception as e:
        logger.error(f"process_update: {e}", exc=e)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        try:
            update = json.loads(body)
            process_update(update)
        except json.JSONDecodeError as e:
            logger.error(f"Webhook bad JSON: {e}")
        except Exception as e:
            logger.error(f"Webhook handler: {e}", exc=e)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Remote Radar is running.")

    def log_message(self, *args):
        pass
