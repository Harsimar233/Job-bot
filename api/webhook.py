"""
Remote Radar — Telegram Webhook
Features: feedback, saved jobs, streak, share, difficulty score, re-engagement
"""
import os, json, time, requests, re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler

BOT_TOKEN    = os.environ.get("JOB_BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
TG_API       = f"https://api.telegram.org/bot{BOT_TOKEN}"
BOT_USERNAME = "RemoteDailyJobBot"
FIND_COOLDOWN = 60

WELCOME = """👋 <b>Welcome to Remote Radar!</b>

Set your preferences once. Get fresh remote job alerts every morning — automatically, free, forever.

🌍 Jobs from 12 sources globally
📂 Every role — Community, Marketing, Tech, Sales, Finance, Executive & more
⏰ Daily alerts at 9am UTC
🔥 Hot jobs flagged if posted in last 24h
💰 Salary & funding info included

Let's set up in 4 quick steps 👇

<i>Made by <a href="https://t.me/Harsimarhs">@Harsimarhs</a> · Feel free to reach out</i>"""

# ── Helpers ───────────────────────────────────────────────────────────────────

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

def sanitize(text, max_len=200):
    if not text:
        return ""
    return re.sub(r"<[^>]+>","",str(text)).strip()[:max_len]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def difficulty_score(job):
    """Job competition level based on source, freshness, role."""
    if job.get("hot"):
        return "🟢 Fresh — apply today"
    source = (job.get("source","") or "").lower()
    title = (job.get("title","") or "").lower()
    niche = any(k in title for k in ["moderator","ambassador","kol","discord mod",
                                      "telegram mod","community","web3","crypto","dao"])
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
            s = str(date_val)
            return s[:10] if len(s) >= 10 else s
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
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        log(f"sb_get error: {e}")
        return []

def sb_post(path, body, prefer="resolution=merge-duplicates"):
    try:
        r = requests.post(f"{SUPABASE_URL}/rest/v1/{path}",
                          headers=_hdr({"Prefer": prefer}), json=body, timeout=10)
        if r.status_code not in (200,201):
            log(f"sb_post error {r.status_code} {path}: {r.text[:100]}")
    except Exception as e:
        log(f"sb_post error: {e}")

def sb_patch(path, body):
    try:
        requests.patch(f"{SUPABASE_URL}/rest/v1/{path}", headers=_hdr(), json=body, timeout=10)
    except Exception as e:
        log(f"sb_patch error: {e}")

def sb_delete(path):
    try:
        requests.delete(f"{SUPABASE_URL}/rest/v1/{path}", headers=_hdr(), timeout=10)
    except Exception as e:
        log(f"sb_delete error: {e}")

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
        last_dt = datetime.fromisoformat(str(last).replace("Z","+00:00"))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last_dt).total_seconds() >= FIND_COOLDOWN
    except Exception:
        return True

def save_job(chat_id, job):
    sb_post("saved_jobs", {
        "chat_id": chat_id,
        "job_id": job.get("job_id",""),
        "job_title": sanitize(job.get("title","")),
        "company": sanitize(job.get("company","")),
        "url": sanitize_url(job.get("url","")),
        "source": sanitize(job.get("source","")),
    }, prefer="resolution=ignore-duplicates")

def save_feedback(chat_id, job_id, feedback):
    sb_post("job_feedback", {"chat_id": chat_id, "job_id": job_id, "feedback": feedback},
            prefer="resolution=merge-duplicates")

# ── Telegram ──────────────────────────────────────────────────────────────────

def send(chat_id, text, keyboard=None, retries=3):
    payload = {"chat_id": chat_id, "text": str(text)[:4096],
                "parse_mode": "HTML", "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    for attempt in range(retries):
        try:
            r = requests.post(f"{TG_API}/sendMessage", json=payload, timeout=10)
            if r.status_code == 200:
                return True
            if r.status_code == 429:
                wait = r.json().get("parameters",{}).get("retry_after",5)
                time.sleep(wait)
                continue
            log(f"send error {r.status_code}: {r.text[:100]}")
            return False
        except Exception as e:
            log(f"send exception: {e}")
            if attempt < retries - 1:
                time.sleep(1)
    return False

def edit(chat_id, msg_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "message_id": msg_id,
                "text": str(text)[:4096], "parse_mode": "HTML"}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    try:
        requests.post(f"{TG_API}/editMessageText", json=payload, timeout=10)
    except Exception as e:
        log(f"edit error: {e}")

def answer(cb_id, text=""):
    try:
        requests.post(f"{TG_API}/answerCallbackQuery",
                      json={"callback_query_id": cb_id, "text": text}, timeout=5)
    except Exception:
        pass

# ── Job formatting ────────────────────────────────────────────────────────────

def format_job_card(job, show_actions=True):
    """Full job card with action buttons for /find flow."""
    hot = "🔥 " if job.get("hot") else ""
    title = sanitize(job.get("title",""))
    company = sanitize(job.get("company",""))
    loc = sanitize(job.get("location",""))
    url = sanitize_url(job.get("url",""))
    source = sanitize(job.get("source",""))
    job_id = job.get("job_id","") or job.get("_id","")

    lines = [f"💼 {hot}<b>{title}</b>"]
    if company:
        lines.append(f"🏢 {company}")
    if loc and loc.lower() not in ("remote",""):
        lines.append(f"📍 {loc}")
    else:
        lines.append("📍 Remote")
    if job.get("salary"):
        lines.append(f"💰 {sanitize(job['salary'])}")
    if job.get("funding"):
        lines.append(f"💸 Funding: {sanitize(job['funding'])}")
    if job.get("visa"):
        lines.append("✈️ Visa sponsorship available")

    # Difficulty score
    diff = difficulty_score(job)
    lines.append(f"📊 {diff}")

    d = fmt_date(job.get("date") or job.get("date_posted",""))
    if d:
        lines.append(f"📅 {d}")
    if url:
        lines.append(f"🔗 <a href='{url}'>Apply Now</a>  •  📌 {source}")

    text = "\n".join(lines)

    # Action buttons
    if show_actions and job_id:
        buttons = [
            [{"text": "👍 Good match", "callback_data": f"like_{job_id}"},
             {"text": "👎 Not relevant", "callback_data": f"dislike_{job_id}"}],
            [{"text": "🔖 Save job", "callback_data": f"save_{job_id}"},
             {"text": "📤 Share", "callback_data": f"share_{job_id}"}],
        ]
        return text, buttons
    return text, None

def format_job_compact(job, show_divider=False):
    """Compact format for grouped daily alerts."""
    hot = "🔥 " if job.get("hot") else ""
    title = sanitize(job.get("title",""))
    company = sanitize(job.get("company",""))
    loc = sanitize(job.get("location",""))
    url = sanitize_url(job.get("url",""))
    source = sanitize(job.get("source",""))

    lines = [f"💼 {hot}<b>{title}</b>"]
    if company:
        lines.append(f"🏢 {company}")
    if loc and loc.lower() not in ("remote",""):
        lines.append(f"📍 {loc}")
    else:
        lines.append("📍 Remote")
    if job.get("salary"):
        lines.append(f"💰 {sanitize(job['salary'])}")
    diff = difficulty_score(job)
    lines.append(f"📊 {diff}")
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
        time.sleep(0.3)

# ── Keyboards ─────────────────────────────────────────────────────────────────

def kb_main():
    return [[{"text": "⚙️ Setup Alerts", "callback_data": "setup_start"}],
            [{"text": "📋 My Preferences", "callback_data": "status"},
             {"text": "⏹ Pause Alerts", "callback_data": "stop"}]]

def kb_seniority():
    return [
        [{"text": "🌱 Entry Level", "callback_data": "sen_entry"},
         {"text": "📈 Mid Level", "callback_data": "sen_mid"}],
        [{"text": "⭐ Senior", "callback_data": "sen_senior"},
         {"text": "👥 Manager / Lead", "callback_data": "sen_manager"}],
        [{"text": "🏆 Director / VP", "callback_data": "sen_director"},
         {"text": "👑 C-Suite", "callback_data": "sen_executive"}],
        [{"text": "🌍 All Levels", "callback_data": "sen_all"}],
    ]

def kb_location():
    return [
        [{"text": "🌍 Remote Only", "callback_data": "loc_remote"}],
        [{"text": "🇺🇸 USA", "callback_data": "loc_usa"},
         {"text": "🇬🇧 UK", "callback_data": "loc_uk"}],
        [{"text": "🇮🇳 India", "callback_data": "loc_india"},
         {"text": "🇳🇬 Nigeria", "callback_data": "loc_nigeria"}],
        [{"text": "🇯🇵 Japan", "callback_data": "loc_japan"},
         {"text": "🇨🇳 China", "callback_data": "loc_china"}],
        [{"text": "🌏 SE Asia", "callback_data": "loc_sea"},
         {"text": "🕌 Middle East", "callback_data": "loc_me"}],
        [{"text": "🇪🇺 Europe", "callback_data": "loc_europe"}],
        [{"text": "🌐 Worldwide / Any", "callback_data": "loc_worldwide"}],
    ]

def kb_company_type():
    return [
        [{"text": "🚀 Startups & Early Stage", "callback_data": "ctype_startup"}],
        [{"text": "🏢 Established Companies", "callback_data": "ctype_established"}],
        [{"text": "🌍 Both / Any", "callback_data": "ctype_any"}],
    ]

def kb_after_jobs():
    return [
        [{"text": "🔍 Find More Jobs", "callback_data": "find_jobs"}],
        [{"text": "🔖 Saved Jobs", "callback_data": "show_saved"},
         {"text": "📋 Preferences", "callback_data": "status"}],
    ]

SEN_LABELS = {
    "entry": "🌱 Entry Level", "mid": "📈 Mid Level", "senior": "⭐ Senior",
    "manager": "👥 Manager / Lead", "director": "🏆 Director / VP",
    "executive": "👑 C-Suite", "all": "🌍 All Levels",
}
LOC_LABELS = {
    "remote": "🌍 Remote Only", "usa": "🇺🇸 USA", "uk": "🇬🇧 UK",
    "india": "🇮🇳 India", "nigeria": "🇳🇬 Nigeria", "japan": "🇯🇵 Japan",
    "china": "🇨🇳 China", "sea": "🌏 SE Asia", "me": "🕌 Middle East",
    "europe": "🇪🇺 Europe", "worldwide": "🌐 Worldwide",
}
CTYPE_LABELS = {
    "startup": "🚀 Startups", "established": "🏢 Established", "any": "🌍 Any",
}
LOC_MAP = {
    "remote": ("Remote", True), "usa": ("USA", False), "uk": ("UK", False),
    "india": ("India", False), "nigeria": ("Nigeria", False),
    "japan": ("Japan", False), "china": ("China", False),
    "sea": ("Southeast Asia", False), "me": ("Middle East", False),
    "europe": ("Europe", False), "worldwide": ("Worldwide", False),
}

# ── Job matching ──────────────────────────────────────────────────────────────

def job_matches_user(job, user):
    try:
        from api.jobs import is_title_relevant, matches_location, matches_seniority
        title = sanitize(job.get("title",""))
        if not is_title_relevant(title, user.get("keywords",""), user.get("category","all")):
            return False
        if not matches_location(job.get("location","Remote"), user.get("location","Remote"),
                                user.get("remote_only", True)):
            return False
        if not matches_seniority(title, user.get("seniority","all")):
            return False
        ctype = user.get("company_type","any")
        if ctype == "startup" and job.get("company_type","") != "startup":
            return False
        if ctype == "established" and job.get("company_type","") == "startup":
            return False
        return True
    except Exception as e:
        log(f"job_matches_user error: {e}")
        return False

# ── Find jobs from cache ──────────────────────────────────────────────────────

def send_jobs_from_cache(chat_id, user):
    if not check_rate_limit(chat_id):
        send(chat_id, f"⏳ Please wait {FIND_COOLDOWN} seconds between searches.")
        return

    send(chat_id, "🔍 Finding matching jobs...")
    update_user(chat_id, {
        "last_find_at": datetime.now(timezone.utc).isoformat(),
        "last_active_at": datetime.now(timezone.utc).isoformat(),
    })

    cached = get_cached_jobs()
    if not cached:
        send(chat_id, "No jobs cached yet. Daily scan runs at 9am UTC.", kb_main())
        return

    from api.jobs import score
    keywords = user.get("keywords","")
    matched = [j for j in cached
               if job_matches_user(j, user) and not was_sent(chat_id, j["job_id"])]
    matched.sort(key=lambda j: (-score(j.get("title",""), keywords), not j.get("hot",False)))
    batch = matched[:5]  # 5 jobs with action buttons

    if not batch:
        send(chat_id,
            "📭 <b>No new jobs found.</b>\n\nYou've seen all matching jobs. "
            "Fresh listings arrive tomorrow at 9am UTC.",
            [[{"text": "⚙️ Change Preferences", "callback_data": "setup_start"},
              {"text": "🔑 Update Keywords", "callback_data": "add_keywords"}]])
        return

    hot_count = sum(1 for j in batch if j.get("hot"))
    sources = list({j["source"] for j in batch})
    header = f"🔍 <b>{len(batch)} jobs matching your profile</b>"
    if hot_count:
        header += f" · 🔥 {hot_count} hot"
    header += f"\nSources: {', '.join(sources[:4])}"
    send(chat_id, header)

    for job in batch:
        text, buttons = format_job_card(job, show_actions=True)
        send(chat_id, text, buttons)
        mark_sent(chat_id, job["job_id"])
        time.sleep(0.2)

    send(chat_id, "✅ Tap a button on any job above to save, share or give feedback.", kb_after_jobs())

# ── Handlers ──────────────────────────────────────────────────────────────────

def handle_start(chat_id, username, ref_code=None):
    existing = get_user(chat_id)
    is_new = not existing
    set_user(chat_id, {
        "username": username or "",
        "active": False,
        "setup_complete": False,
        "category": "all",
        "seniority": "all",
        "keywords": "",
        "location": "Worldwide",
        "location_key": "worldwide",
        "remote_only": False,
        "company_type": "any",
        "awaiting_keywords": False,
        "awaiting_role": False,
        "streak": existing.get("streak",0) if existing else 0,
        "referrals": existing.get("referrals",0) if existing else 0,
        "referred_by": existing.get("referred_by") if existing else None,
    })
    if is_new and ref_code and ref_code.startswith("ref_"):
        try:
            referrer_id = int(ref_code.replace("ref_",""))
            if referrer_id != chat_id:
                update_user(chat_id, {"referred_by": referrer_id})
                inc_referrals(referrer_id)
                ref = get_user(referrer_id)
                count = ref.get("referrals",0)
                send(referrer_id,
                    f"🎉 Someone joined using your invite link!\n\n"
                    f"👥 You've referred <b>{count}</b> {'person' if count==1 else 'people'}.\n\n"
                    f"Keep sharing: <code>t.me/{BOT_USERNAME}?start=ref_{referrer_id}</code>")
        except Exception as e:
            log(f"referral error: {e}")
    send(chat_id, WELCOME, kb_main())

def handle_status(chat_id):
    user = get_user(chat_id)
    if not user or not user.get("setup_complete"):
        send(chat_id, "You haven't set up alerts yet.", kb_main())
        return
    kws = user.get("keywords","") or "None set"
    status = "✅ Active" if user.get("active") else "⏸ Paused"
    referrals = user.get("referrals",0) or 0
    streak = user.get("streak",0) or 0
    invite = f"t.me/{BOT_USERNAME}?start=ref_{chat_id}"
    streak_text = f"🔥 {streak} day streak!" if streak > 1 else ""
    send(chat_id,
        f"📋 <b>Your Alert Preferences</b>\n\n"
        f"🎯 Role/Keywords: {kws}\n"
        f"🎓 {SEN_LABELS.get(user.get('seniority','all'),'All Levels')}\n"
        f"📍 {LOC_LABELS.get(user.get('location_key','worldwide'),'Worldwide')}\n"
        f"🏢 {CTYPE_LABELS.get(user.get('company_type','any'),'Any')}\n"
        f"📡 Status: {status}\n"
        + (f"{streak_text}\n" if streak_text else "") +
        f"\n👥 Referrals: <b>{referrals}</b>\n"
        f"🔗 <code>{invite}</code>",
        [[{"text": "✏️ Change Preferences", "callback_data": "setup_start"},
          {"text": "⏹ Pause", "callback_data": "stop"}],
         [{"text": "🔍 Find Jobs Now", "callback_data": "find_jobs"},
          {"text": "🔖 Saved Jobs", "callback_data": "show_saved"}],
         [{"text": "👥 Invite Friends", "callback_data": "invite"}]])

def handle_saved(chat_id):
    saved = sb_get(f"saved_jobs?chat_id=eq.{chat_id}&select=*&order=created_at.desc&limit=10")
    if not saved:
        send(chat_id,
            "🔖 <b>No saved jobs yet.</b>\n\n"
            "When browsing jobs, tap <b>🔖 Save job</b> to bookmark it here.",
            [[{"text": "🔍 Find Jobs Now", "callback_data": "find_jobs"}]])
        return
    send(chat_id, f"🔖 <b>Your Saved Jobs ({len(saved)})</b>\n")
    for j in saved:
        url = sanitize_url(j.get("url",""))
        title = sanitize(j.get("job_title",""))
        company = sanitize(j.get("company",""))
        source = sanitize(j.get("source",""))
        line = f"💼 <b>{title}</b>\n🏢 {company}\n"
        if url:
            line += f"🔗 <a href='{url}'>Apply Now</a>  •  📌 {source}"
        send(chat_id, line)
        time.sleep(0.2)

def handle_invite(chat_id):
    user = get_user(chat_id)
    referrals = user.get("referrals",0) or 0
    invite = f"t.me/{BOT_USERNAME}?start=ref_{chat_id}"
    send(chat_id,
        f"👥 <b>Invite Friends to Remote Radar</b>\n\n"
        f"🔗 Your invite link:\n<code>{invite}</code>\n\n"
        f"📊 People invited: <b>{referrals}</b>\n\n"
        f"<i>Get daily remote job alerts on Telegram — free forever. "
        f"Setup takes 60 seconds: {invite}</i>")

def handle_stop(chat_id):
    update_user(chat_id, {"active": False})
    send(chat_id, "⏸ Alerts paused. Tap below to restart.",
         [[{"text": "▶️ Restart Alerts", "callback_data": "setup_start"}]])

def handle_delete(chat_id):
    sb_delete(f"users?chat_id=eq.{chat_id}")
    sb_delete(f"sent_jobs?chat_id=eq.{chat_id}")
    sb_delete(f"watchlist?chat_id=eq.{chat_id}")
    sb_delete(f"saved_jobs?chat_id=eq.{chat_id}")
    sb_delete(f"job_feedback?chat_id=eq.{chat_id}")
    send(chat_id, "🗑 All your data has been deleted. Send /start anytime to set up again.")

def handle_watch(chat_id, text):
    company = sanitize(text.replace("/watch","").strip())
    if not company:
        send(chat_id, "Usage: <code>/watch Coinbase</code>")
        return
    sb_post("watchlist", {"chat_id": chat_id, "company": company},
            prefer="resolution=ignore-duplicates")
    send(chat_id, f"👁 Now watching <b>{company}</b> — you'll be alerted when they post new jobs.")

def step1_role(chat_id, msg_id):
    edit(chat_id, msg_id,
         "⚙️ <b>Step 1 of 4 — Your Role</b>\n\n"
         "What job role are you looking for?\n\n"
         "<b>Examples:</b>\n"
         "• <code>Community Manager</code>\n"
         "• <code>Web3 Marketing Manager</code>\n"
         "• <code>Discord Moderator</code>\n"
         "• <code>Software Engineer</code>\n"
         "• <code>Customer Support</code>\n\n"
         "Just type your role below and send 👇",
         [[{"text": "❌ Cancel", "callback_data": "status"}]])

def step2_seniority(chat_id, role):
    send(chat_id,
         f"✅ Role: <b>{role}</b>\n\n"
         f"⚙️ <b>Step 2 of 4 — Seniority Level</b>\n\nWhat level are you targeting?",
         kb_seniority())

def step3_location(chat_id, msg_id, seniority, cb_id):
    answer(cb_id, f"✅ {SEN_LABELS.get(seniority, seniority)}")
    update_user(chat_id, {"seniority": seniority})
    edit(chat_id, msg_id,
         f"✅ Level: {SEN_LABELS.get(seniority, seniority)}\n\n"
         f"⚙️ <b>Step 3 of 4 — Location</b>\n\nWhere are you looking to work?",
         kb_location())

def step4_company_type(chat_id, msg_id, loc_key, cb_id):
    loc_name, remote_only = LOC_MAP.get(loc_key, ("Worldwide", False))
    answer(cb_id, f"✅ {LOC_LABELS.get(loc_key, loc_key)}")
    update_user(chat_id, {"location": loc_name, "location_key": loc_key, "remote_only": remote_only})
    edit(chat_id, msg_id,
         f"✅ Location: {LOC_LABELS.get(loc_key, loc_key)}\n\n"
         f"⚙️ <b>Step 4 of 4 — Company Type</b>\n\nWhat kind of company do you prefer?",
         kb_company_type())

def finish_setup(chat_id, msg_id, ctype, cb_id):
    answer(cb_id, f"✅ {CTYPE_LABELS.get(ctype, ctype)}")
    update_user(chat_id, {"company_type": ctype, "active": True, "setup_complete": True})
    user = get_user(chat_id)
    invite = f"t.me/{BOT_USERNAME}?start=ref_{chat_id}"
    send(chat_id,
        f"🎉 <b>All set! Your daily alerts are live.</b>\n\n"
        f"🎯 Role: {user.get('keywords','')}\n"
        f"🎓 {SEN_LABELS.get(user.get('seniority','all'),'All Levels')}\n"
        f"📍 {LOC_LABELS.get(user.get('location_key','worldwide'),'Worldwide')}\n"
        f"🏢 {CTYPE_LABELS.get(ctype,'Any')}\n\n"
        f"👥 Share: <code>{invite}</code>",
        [[{"text": "🔍 Find Jobs Now", "callback_data": "find_jobs"},
          {"text": "👥 Invite Friends", "callback_data": "invite"}]])

def handle_keywords(chat_id, text):
    keywords = sanitize(text.replace("/keywords","").strip().lstrip(","))
    if not keywords:
        update_user(chat_id, {"awaiting_keywords": True})
        send(chat_id,
             "✏️ <b>Update Keywords</b>\n\nType your keywords and send:\n\n"
             "• <code>community manager, web3</code>\n"
             "• <code>ambassador, discord mod, kol</code>")
        return
    update_user(chat_id, {"keywords": keywords, "awaiting_keywords": False})
    send(chat_id, f"✅ Keywords updated: <b>{keywords}</b>")
    user = get_user(chat_id)
    send_jobs_from_cache(chat_id, user)

# ── Main processor ────────────────────────────────────────────────────────────

def process_update(update):
    try:
        if "message" in update:
            msg = update["message"]
            chat_id = msg["chat"]["id"]
            username = msg.get("from",{}).get("username","")
            text = msg.get("text","") or ""

            if text and not text.startswith("/"):
                user = get_user(chat_id)
                # Step 1: Role input
                if user.get("awaiting_role"):
                    role = sanitize(text.strip())
                    update_user(chat_id, {"keywords": role, "category": "all", "awaiting_role": False})
                    step2_seniority(chat_id, role)
                    return
                # Keyword update
                if user.get("awaiting_keywords"):
                    kw = sanitize(text.strip())
                    update_user(chat_id, {"keywords": kw, "awaiting_keywords": False})
                    send(chat_id, f"✅ Keywords updated: <b>{kw}</b>")
                    send_jobs_from_cache(chat_id, user)
                    return

            if text.startswith("/start"):
                parts = text.split(" ",1)
                ref = parts[1].strip() if len(parts) > 1 else None
                handle_start(chat_id, username, ref)
            elif text.startswith("/keywords"):
                handle_keywords(chat_id, text)
            elif text.startswith("/find"):
                user = get_user(chat_id)
                if user.get("setup_complete"):
                    send_jobs_from_cache(chat_id, user)
                else:
                    send(chat_id, "Please set up your preferences first.", kb_main())
            elif text.startswith("/saved"):
                handle_saved(chat_id)
            elif text.startswith("/watch "):
                handle_watch(chat_id, text)
            elif text.startswith("/invite") or text.startswith("/refer"):
                handle_invite(chat_id)
            elif text.startswith("/stop"):
                handle_stop(chat_id)
            elif text.startswith("/status"):
                handle_status(chat_id)
            elif text.startswith("/setup"):
                send(chat_id, "Let's update your preferences:", kb_main())
            elif text.startswith("/delete"):
                send(chat_id, "⚠️ This deletes all your data. Are you sure?",
                     [[{"text": "🗑 Yes, delete", "callback_data": "confirm_delete"},
                       {"text": "Cancel", "callback_data": "status"}]])
            elif text.startswith("/help"):
                send(chat_id,
                    "📖 <b>Remote Radar Commands</b>\n\n"
                    "/start — Welcome & setup\n"
                    "/setup — Change preferences\n"
                    "/keywords — Update role keywords\n"
                    "/find — Find jobs right now\n"
                    "/saved — View bookmarked jobs\n"
                    "/watch Coinbase — Watch a company\n"
                    "/invite — Get your invite link\n"
                    "/status — View preferences & streak\n"
                    "/stop — Pause alerts\n"
                    "/delete — Delete your account\n"
                    "/help — This message")

        elif "callback_query" in update:
            cb = update["callback_query"]
            chat_id = cb["from"]["id"]
            username = cb["from"].get("username","")
            msg_id = cb["message"]["message_id"]
            data = cb.get("data","")
            cb_id = cb["id"]

            if not get_user(chat_id):
                set_user(chat_id, {"username": username, "active": False, "setup_complete": False})

            # Job action callbacks
            if data.startswith("like_"):
                job_id = data.replace("like_","")
                save_feedback(chat_id, job_id, "like")
                answer(cb_id, "👍 Thanks! We'll show more like this.")

            elif data.startswith("dislike_"):
                job_id = data.replace("dislike_","")
                save_feedback(chat_id, job_id, "dislike")
                answer(cb_id, "👎 Got it. We'll filter these out.")

            elif data.startswith("save_"):
                job_id = data.replace("save_","")
                # Find job in cache
                cached = sb_get(f"jobs?job_id=eq.{job_id}&select=*&limit=1")
                if cached:
                    save_job(chat_id, cached[0])
                    answer(cb_id, "🔖 Job saved! View with /saved")
                else:
                    answer(cb_id, "Could not save — job not found.")

            elif data.startswith("share_"):
                job_id = data.replace("share_","")
                cached = sb_get(f"jobs?job_id=eq.{job_id}&select=*&limit=1")
                answer(cb_id)
                if cached:
                    j = cached[0]
                    invite = f"t.me/{BOT_USERNAME}?start=ref_{chat_id}"
                    url = sanitize_url(j.get("url",""))
                    title = sanitize(j.get("title",""))
                    company = sanitize(j.get("company",""))
                    send(chat_id,
                        f"📤 <b>Share this job:</b>\n\n"
                        f"💼 {title} at {company}\n"
                        f"🔗 {url}\n\n"
                        f"Find more remote jobs daily: {invite}")

            elif data == "setup_start":
                answer(cb_id)
                update_user(chat_id, {"awaiting_role": True})
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
                step3_location(chat_id, msg_id, data.replace("sen_",""), cb_id)
            elif data.startswith("loc_"):
                step4_company_type(chat_id, msg_id, data.replace("loc_",""), cb_id)
            elif data.startswith("ctype_"):
                finish_setup(chat_id, msg_id, data.replace("ctype_",""), cb_id)

    except Exception as e:
        log(f"process_update error: {e}")


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            process_update(json.loads(body))
        except Exception as e:
            log(f"webhook error: {e}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Remote Radar is running.")

    def log_message(self, *args):
        pass
