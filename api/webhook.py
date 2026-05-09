"""
Remote Radar — Telegram Webhook
All job fetching pulls from Supabase — no scraping on webhook.
"""
import os, json, requests
from datetime import datetime
from http.server import BaseHTTPRequestHandler

BOT_TOKEN    = os.environ.get("JOB_BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
TG_API       = f"https://api.telegram.org/bot{BOT_TOKEN}"
BOT_USERNAME = "RemoteDailyJobBot"

WELCOME = """👋 <b>Welcome to Remote Radar!</b>

Set your preferences once. Get fresh remote job alerts every morning — automatically, free, forever.

🌍 Jobs from 12 sources globally
📂 Every category — Tech, Marketing, Community, Sales, Finance, Executive & more
⏰ Daily alerts at 9am UTC — zero effort after setup
🔥 Hot jobs flagged if posted in last 24 hours
💰 Salary & funding info included

💡 After setup, use /keywords for specific roles:
<code>ambassador, kol manager, discord mod, telegram mod</code>

Let's set up in 4 quick steps 👇

<i>Made by <a href="https://t.me/Harsimarhs">@Harsimarhs</a> · Feel free to reach out</i>"""

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
    except Exception:
        return []

def sb_post(path, body, prefer="resolution=merge-duplicates"):
    try:
        requests.post(f"{SUPABASE_URL}/rest/v1/{path}",
                      headers=_hdr({"Prefer": prefer}), json=body, timeout=10)
    except Exception:
        pass

def sb_patch(path, body):
    try:
        requests.patch(f"{SUPABASE_URL}/rest/v1/{path}",
                       headers=_hdr(), json=body, timeout=10)
    except Exception:
        pass

def sb_delete(path):
    try:
        requests.delete(f"{SUPABASE_URL}/rest/v1/{path}", headers=_hdr(), timeout=10)
    except Exception:
        pass

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

def get_all_cached_jobs():
    """Pull all jobs stored by daily scan — instant, no scraping."""
    return sb_get("jobs?select=*&order=scraped_at.desc&limit=2000")

def inc_referrals(chat_id):
    user = get_user(chat_id)
    update_user(chat_id, {"referrals": (user.get("referrals") or 0) + 1})

# ── Telegram ──────────────────────────────────────────────────────────────────

def send(chat_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "text": str(text)[:4096],
                "parse_mode": "HTML", "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    try:
        requests.post(f"{TG_API}/sendMessage", json=payload, timeout=10)
    except Exception:
        pass

def edit(chat_id, msg_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "message_id": msg_id,
                "text": str(text)[:4096], "parse_mode": "HTML"}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    try:
        requests.post(f"{TG_API}/editMessageText", json=payload, timeout=10)
    except Exception:
        pass

def answer(cb_id, text=""):
    try:
        requests.post(f"{TG_API}/answerCallbackQuery",
                      json={"callback_query_id": cb_id, "text": text}, timeout=5)
    except Exception:
        pass

# ── Keyboards ─────────────────────────────────────────────────────────────────

def kb_main():
    return [[{"text": "⚙️ Setup Alerts", "callback_data": "setup_start"}],
            [{"text": "📋 My Preferences", "callback_data": "status"},
             {"text": "⏹ Pause Alerts", "callback_data": "stop"}]]

def kb_category():
    return [
        [{"text": "💻 Tech & Engineering", "callback_data": "cat_tech"}],
        [{"text": "📦 Product Management", "callback_data": "cat_product"}],
        [{"text": "🎨 Design & Creative", "callback_data": "cat_design"}],
        [{"text": "📣 Marketing & Growth", "callback_data": "cat_marketing"}],
        [{"text": "🌐 Community & Social Media", "callback_data": "cat_community"}],
        [{"text": "💬 Customer Support", "callback_data": "cat_support"}],
        [{"text": "💼 Sales & Business Dev", "callback_data": "cat_sales"}],
        [{"text": "💰 Finance & Accounting", "callback_data": "cat_finance"}],
        [{"text": "⚙️ Operations & HR", "callback_data": "cat_operations"}],
        [{"text": "👔 Executive (CEO, CMO, VP+)", "callback_data": "cat_executive"}],
        [{"text": "🔗 Web3 & Crypto", "callback_data": "cat_web3"}],
        [{"text": "🌍 All Categories", "callback_data": "cat_all"}],
    ]

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
        [{"text": "📋 My Preferences", "callback_data": "status"},
         {"text": "🔑 Add Keywords", "callback_data": "add_keywords"}],
    ]

# ── Label maps ────────────────────────────────────────────────────────────────

CAT_LABELS = {
    "tech": "💻 Tech & Engineering", "product": "📦 Product Management",
    "design": "🎨 Design & Creative", "marketing": "📣 Marketing & Growth",
    "community": "🌐 Community & Social Media", "support": "💬 Customer Support",
    "sales": "💼 Sales & Business Dev", "finance": "💰 Finance & Accounting",
    "operations": "⚙️ Operations & HR", "executive": "👔 Executive",
    "web3": "🔗 Web3 & Crypto", "all": "🌍 All Categories",
}
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

# ── Job matching (for cached jobs from Supabase) ──────────────────────────────

def job_matches_user(job, user):
    """Match a cached Supabase job row against user preferences."""
    from api.jobs import is_title_relevant, matches_location, matches_seniority
    title = job.get("title","")
    keywords = user.get("keywords","")
    category = user.get("category","all")
    location = user.get("location","Remote")
    remote_only = user.get("remote_only", True)
    seniority = user.get("seniority","all")
    if not is_title_relevant(title, keywords, category):
        return False
    if not matches_location(job.get("location","Remote"), location, remote_only):
        return False
    if not matches_seniority(title, seniority):
        return False
    return True

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

# ── Find jobs from Supabase cache ─────────────────────────────────────────────

def send_jobs_from_cache(chat_id, user):
    from api.jobs import score
    send(chat_id, "🔍 Finding matching jobs...")

    cached = get_all_cached_jobs()
    if not cached:
        send(chat_id,
            "No jobs in cache yet. The daily scan runs at 9am UTC. "
            "Come back then or ask @Harsimarhs to run it manually.",
            [[{"text": "⚙️ Update Preferences", "callback_data": "setup_start"}]])
        return

    keywords = user.get("keywords","")
    matched = [j for j in cached
               if job_matches_user(j, user)
               and not was_sent(chat_id, j["job_id"])]

    matched.sort(key=lambda j: (-score(j.get("title",""), keywords),
                                not j.get("hot", False)))
    batch = matched[:10]

    if not batch:
        send(chat_id,
            "📭 <b>No new jobs found.</b>\n\n"
            "You've seen all matching jobs from today's scan. "
            "Fresh listings arrive tomorrow at 9am UTC.",
            [[{"text": "⚙️ Change Preferences", "callback_data": "setup_start"},
              {"text": "🔑 Update Keywords", "callback_data": "add_keywords"}]])
        return

    sources = list({j["source"] for j in batch})
    hot_count = sum(1 for j in batch if j.get("hot"))
    header = f"🔍 <b>{len(batch)} jobs matching your profile</b>"
    if hot_count:
        header += f" · 🔥 {hot_count} hot"
    header += f"\nSources: {', '.join(sources)}"
    send(chat_id, header)

    new_ids = []
    for job in batch:
        send(chat_id, format_job(job))
        new_ids.append(job["job_id"])

    for jid in new_ids:
        mark_sent(chat_id, jid)

    send(chat_id,
        f"✅ <b>That's your batch.</b>\n\nTap below for more anytime.",
        kb_after_jobs())

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
        "awaiting_cover": False,
        "referrals": existing.get("referrals", 0) if existing else 0,
        "referred_by": existing.get("referred_by") if existing else None,
    })
    if is_new and ref_code and ref_code.startswith("ref_"):
        try:
            referrer_id = int(ref_code.replace("ref_",""))
            if referrer_id != chat_id:
                update_user(chat_id, {"referred_by": referrer_id})
                inc_referrals(referrer_id)
                ref = get_user(referrer_id)
                count = ref.get("referrals", 0)
                send(referrer_id,
                    f"🎉 Someone joined using your invite link!\n\n"
                    f"👥 You've now referred <b>{count}</b> {'person' if count==1 else 'people'}.\n\n"
                    f"Keep sharing: <code>t.me/{BOT_USERNAME}?start=ref_{referrer_id}</code>")
        except Exception:
            pass
    send(chat_id, WELCOME, kb_main())

def handle_status(chat_id):
    user = get_user(chat_id)
    if not user or not user.get("setup_complete"):
        send(chat_id, "You haven't set up alerts yet.", kb_main())
        return
    kws = user.get("keywords","") or "None set"
    status = "✅ Active" if user.get("active") else "⏸ Paused"
    referrals = user.get("referrals",0) or 0
    invite = f"t.me/{BOT_USERNAME}?start=ref_{chat_id}"
    send(chat_id,
        f"📋 <b>Your Alert Preferences</b>\n\n"
        f"📂 {CAT_LABELS.get(user.get('category','all'),'All')}\n"
        f"🎯 {SEN_LABELS.get(user.get('seniority','all'),'All Levels')}\n"
        f"📍 {LOC_LABELS.get(user.get('location_key','worldwide'),'Worldwide')}\n"
        f"🏢 {CTYPE_LABELS.get(user.get('company_type','any'),'Any')}\n"
        f"🔑 Keywords: {kws}\n"
        f"📡 Status: {status}\n\n"
        f"👥 Referrals: <b>{referrals}</b>\n"
        f"🔗 <code>{invite}</code>\n\n"
        f"Alerts arrive daily at 9am UTC.",
        [[{"text": "✏️ Change Preferences", "callback_data": "setup_start"},
          {"text": "⏹ Pause", "callback_data": "stop"}],
         [{"text": "🔍 Find Jobs Now", "callback_data": "find_jobs"},
          {"text": "👥 Invite Friends", "callback_data": "invite"}]])

def handle_invite(chat_id):
    user = get_user(chat_id)
    referrals = user.get("referrals",0) or 0
    invite = f"t.me/{BOT_USERNAME}?start=ref_{chat_id}"
    send(chat_id,
        f"👥 <b>Invite Friends to Remote Radar</b>\n\n"
        f"Share your link and get notified when someone joins!\n\n"
        f"🔗 Your link:\n<code>{invite}</code>\n\n"
        f"📊 People invited: <b>{referrals}</b>\n\n"
        f"<i>I use this free bot to get daily remote job alerts — no spam, just relevant jobs every morning. "
        f"Check it out: {invite}</i>")

def handle_stop(chat_id):
    update_user(chat_id, {"active": False})
    send(chat_id, "⏸ Alerts paused.\n\nTap below to restart.",
         [[{"text": "▶️ Restart Alerts", "callback_data": "setup_start"}]])

def step1(chat_id, msg_id):
    edit(chat_id, msg_id,
         "⚙️ <b>Step 1 of 4 — Job Category</b>\n\nWhat type of jobs are you looking for?",
         kb_category())

def step2(chat_id, msg_id, category, cb_id):
    answer(cb_id, f"✅ {CAT_LABELS.get(category, category)}")
    update_user(chat_id, {"category": category})
    edit(chat_id, msg_id,
         f"✅ Category: {CAT_LABELS.get(category, category)}\n\n"
         f"⚙️ <b>Step 2 of 4 — Seniority Level</b>\n\nWhat level are you targeting?",
         kb_seniority())

def step3(chat_id, msg_id, seniority, cb_id):
    answer(cb_id, f"✅ {SEN_LABELS.get(seniority, seniority)}")
    update_user(chat_id, {"seniority": seniority})
    edit(chat_id, msg_id,
         f"✅ Level: {SEN_LABELS.get(seniority, seniority)}\n\n"
         f"⚙️ <b>Step 3 of 4 — Location</b>\n\nWhere are you looking to work?",
         kb_location())

def step4(chat_id, msg_id, loc_key, cb_id):
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
        f"📂 {CAT_LABELS.get(user.get('category','all'),'All Categories')}\n"
        f"🎯 {SEN_LABELS.get(user.get('seniority','all'),'All Levels')}\n"
        f"📍 {LOC_LABELS.get(user.get('location_key','worldwide'),'Worldwide')}\n"
        f"🏢 {CTYPE_LABELS.get(ctype,'Any')}\n\n"
        f"💡 Add keywords: <code>/keywords ambassador, kol manager, discord mod</code>\n\n"
        f"👥 Share with friends:\n<code>{invite}</code>",
        [[{"text": "🔍 Find Jobs Now", "callback_data": "find_jobs"},
          {"text": "👥 Invite Friends", "callback_data": "invite"}]])

def handle_keywords(chat_id, text):
    keywords = text.replace("/keywords","").strip().lstrip(",").strip()
    if not keywords:
        update_user(chat_id, {"awaiting_keywords": True})
        send(chat_id,
             "✏️ <b>Add Keywords</b>\n\nType your keywords and send:\n\n"
             "• <code>moderator, community manager</code>\n"
             "• <code>ambassador, kol manager, discord mod</code>\n"
             "• <code>zealy, galxe, telegram moderator</code>")
        return
    update_user(chat_id, {"keywords": keywords, "awaiting_keywords": False})
    send(chat_id, f"✅ Keywords saved: <b>{keywords}</b>")
    user = get_user(chat_id)
    send_jobs_from_cache(chat_id, user)

def handle_find(chat_id):
    user = get_user(chat_id)
    if not user.get("setup_complete"):
        send(chat_id, "Please set up your preferences first.", kb_main())
        return
    send_jobs_from_cache(chat_id, user)

def handle_watch(chat_id, text):
    company = text.replace("/watch","").strip()
    if not company:
        send(chat_id, "Usage: <code>/watch Coinbase</code>\n\nI'll alert you when that company posts new jobs.")
        return
    sb_post("watchlist", {"chat_id": chat_id, "company": company},
            prefer="resolution=ignore-duplicates")
    send(chat_id, f"👁 Watching <b>{company}</b>\n\nYou'll be notified when they post new jobs.")

# ── Main processor ────────────────────────────────────────────────────────────

def process_update(update):
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        username = msg.get("from",{}).get("username","")
        text = msg.get("text","") or ""

        if text and not text.startswith("/"):
            user = get_user(chat_id)
            if user.get("awaiting_keywords"):
                update_user(chat_id, {"keywords": text.strip(), "awaiting_keywords": False})
                send(chat_id, f"✅ Keywords saved: <b>{text.strip()}</b>")
                send_jobs_from_cache(chat_id, user)
                return

        if text.startswith("/start"):
            parts = text.split(" ", 1)
            ref = parts[1].strip() if len(parts) > 1 else None
            handle_start(chat_id, username, ref)
        elif text.startswith("/keywords"):
            handle_keywords(chat_id, text)
        elif text.startswith("/find"):
            handle_find(chat_id)
        elif text.startswith("/watch"):
            handle_watch(chat_id, text)
        elif text.startswith("/invite") or text.startswith("/refer"):
            handle_invite(chat_id)
        elif text.startswith("/stop"):
            handle_stop(chat_id)
        elif text.startswith("/status"):
            handle_status(chat_id)
        elif text.startswith("/setup"):
            send(chat_id, "Let's update your preferences:", kb_main())
        elif text.startswith("/help"):
            send(chat_id,
                "📖 <b>Remote Radar Commands</b>\n\n"
                "/start — Welcome & setup\n"
                "/setup — Change preferences\n"
                "/keywords — Add role keywords\n"
                "/find — Find jobs right now\n"
                "/watch Coinbase — Watch a company\n"
                "/invite — Get your invite link\n"
                "/status — View preferences\n"
                "/stop — Pause alerts\n"
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

        if data == "setup_start":
            answer(cb_id)
            step1(chat_id, msg_id)
        elif data == "find_jobs":
            answer(cb_id, "Searching...")
            user = get_user(chat_id)
            send_jobs_from_cache(chat_id, user)
        elif data == "invite":
            answer(cb_id)
            handle_invite(chat_id)
        elif data == "add_keywords":
            answer(cb_id)
            update_user(chat_id, {"awaiting_keywords": True})
            send(chat_id,
                "✏️ <b>Add Keywords</b>\n\nType your keywords and send:\n\n"
                "• <code>moderator, community manager</code>\n"
                "• <code>ambassador, kol manager, discord mod</code>")
        elif data == "status":
            answer(cb_id)
            handle_status(chat_id)
        elif data == "stop":
            answer(cb_id)
            handle_stop(chat_id)
        elif data.startswith("cat_"):
            step2(chat_id, msg_id, data.replace("cat_",""), cb_id)
        elif data.startswith("sen_"):
            step3(chat_id, msg_id, data.replace("sen_",""), cb_id)
        elif data.startswith("loc_"):
            step4(chat_id, msg_id, data.replace("loc_",""), cb_id)
        elif data.startswith("ctype_"):
            finish_setup(chat_id, msg_id, data.replace("ctype_",""), cb_id)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            process_update(json.loads(body))
        except Exception as e:
            print(f"Webhook error: {e}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Remote Radar is running.")

    def log_message(self, *args):
        pass
