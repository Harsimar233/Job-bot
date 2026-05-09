"""
Remote Radar — Public Telegram Bot Webhook with Referral System
"""
import os, json, requests
from http.server import BaseHTTPRequestHandler

BOT_TOKEN    = os.environ.get("JOB_BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
TG_API       = f"https://api.telegram.org/bot{BOT_TOKEN}"
BOT_USERNAME = "RemoteDailyJobBot"

WELCOME = """👋 <b>Welcome to Remote Radar!</b>

Set your preferences once. We send you fresh remote job alerts every morning — automatically, free, forever.

🌍 Jobs from 9 sources globally
📂 Every category — Tech, Marketing, Sales, Finance, Executive & more
⏰ Daily alerts at 9am UTC — no manual searching ever again
⚡ Personalised to your exact preferences

💡 After setup, use /keywords to target specific roles like:
<code>ambassador, kol manager, discord moderator, telegram mod</code>

Let's set up in 4 quick steps 👇

<i>Made by <a href="https://t.me/Harsimarhs">@Harsimarhs</a> · Feel free to reach out for any queries</i>"""

def db_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

def db_get(chat_id):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?chat_id=eq.{chat_id}&select=*",
        headers=db_headers(), timeout=10)
    data = r.json()
    return data[0] if data else {}

def db_set(chat_id, data):
    data["chat_id"] = chat_id
    requests.post(f"{SUPABASE_URL}/rest/v1/users",
                  headers=db_headers(), json=data, timeout=10)

def db_update(chat_id, data):
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/users?chat_id=eq.{chat_id}",
        headers=db_headers(), json=data, timeout=10)

def db_increment_referrals(chat_id):
    user = db_get(chat_id)
    current = user.get("referrals", 0) or 0
    db_update(chat_id, {"referrals": current + 1})

def get_sent_ids(chat_id):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/sent_jobs?chat_id=eq.{chat_id}&select=job_id",
        headers=db_headers(), timeout=10)
    return {row["job_id"] for row in r.json()} if r.status_code == 200 else set()

def mark_sent(chat_id, job_ids):
    if not job_ids:
        return
    requests.post(
        f"{SUPABASE_URL}/rest/v1/sent_jobs",
        headers={**db_headers(), "Prefer": "resolution=ignore-duplicates"},
        json=[{"chat_id": chat_id, "job_id": jid} for jid in job_ids],
        timeout=10)

def send(chat_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    requests.post(f"{TG_API}/sendMessage", json=payload, timeout=10)

def edit(chat_id, msg_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "message_id": msg_id,
                "text": text, "parse_mode": "HTML"}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    requests.post(f"{TG_API}/editMessageText", json=payload, timeout=10)

def answer(cb_id, text=""):
    requests.post(f"{TG_API}/answerCallbackQuery",
                  json={"callback_query_id": cb_id, "text": text}, timeout=5)

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

def kb_main():
    return [
        [{"text": "⚙️ Setup Alerts", "callback_data": "setup_start"}],
        [{"text": "📋 My Preferences", "callback_data": "status"},
         {"text": "⏹ Pause Alerts", "callback_data": "stop"}],
    ]

def kb_after_jobs():
    return [
        [{"text": "🔍 Find More Jobs", "callback_data": "find_jobs"}],
        [{"text": "📋 My Preferences", "callback_data": "status"},
         {"text": "🔑 Add Keywords", "callback_data": "add_keywords"}],
    ]

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

def handle_start(chat_id, username, ref_code=None):
    existing = db_get(chat_id)
    is_new = not existing

    db_set(chat_id, {
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
        "referrals": existing.get("referrals", 0) if existing else 0,
        "referred_by": existing.get("referred_by") if existing else None,
    })

    # Handle referral
    if is_new and ref_code and ref_code.startswith("ref_"):
        try:
            referrer_id = int(ref_code.replace("ref_", ""))
            if referrer_id != chat_id:
                db_update(chat_id, {"referred_by": referrer_id})
                db_increment_referrals(referrer_id)
                # Notify referrer
                referrer = db_get(referrer_id)
                ref_count = referrer.get("referrals", 0)
                send(referrer_id,
                    f"🎉 Someone joined Remote Radar using your invite link!\n\n"
                    f"👥 You've now referred <b>{ref_count}</b> {'person' if ref_count == 1 else 'people'}.\n\n"
                    f"Keep sharing: <code>t.me/{BOT_USERNAME}?start=ref_{referrer_id}</code>")
        except Exception as e:
            print(f"Referral error: {e}")

    send(chat_id, WELCOME, kb_main())

def handle_status(chat_id):
    user = db_get(chat_id)
    if not user or not user.get("setup_complete"):
        send(chat_id, "You haven't set up alerts yet. Tap below to get started.", kb_main())
        return
    status = "✅ Active" if user.get("active") else "⏸ Paused"
    kws = user.get("keywords", "") or "None set"
    referrals = user.get("referrals", 0) or 0
    invite_link = f"t.me/{BOT_USERNAME}?start=ref_{chat_id}"
    send(chat_id,
        f"📋 <b>Your Alert Preferences</b>\n\n"
        f"📂 Category: {CAT_LABELS.get(user.get('category','all'), 'All')}\n"
        f"🎯 Level: {SEN_LABELS.get(user.get('seniority','all'), 'All')}\n"
        f"📍 Location: {LOC_LABELS.get(user.get('location_key','worldwide'), 'Worldwide')}\n"
        f"🏢 Company: {CTYPE_LABELS.get(user.get('company_type','any'), 'Any')}\n"
        f"🔑 Keywords: {kws}\n"
        f"📡 Status: {status}\n\n"
        f"👥 <b>Your Referrals: {referrals}</b>\n"
        f"🔗 Invite link: <code>{invite_link}</code>\n\n"
        f"Alerts arrive daily at 9am UTC.",
        [[{"text": "✏️ Change Preferences", "callback_data": "setup_start"},
          {"text": "⏹ Pause", "callback_data": "stop"}],
         [{"text": "🔍 Find Jobs Now", "callback_data": "find_jobs"},
          {"text": "👥 My Invite Link", "callback_data": "invite"}]]
    )

def handle_invite(chat_id):
    user = db_get(chat_id)
    referrals = user.get("referrals", 0) or 0
    invite_link = f"t.me/{BOT_USERNAME}?start=ref_{chat_id}"
    send(chat_id,
        f"👥 <b>Invite Friends to Remote Radar</b>\n\n"
        f"Share your personal invite link and get notified every time someone joins!\n\n"
        f"🔗 Your link:\n<code>{invite_link}</code>\n\n"
        f"📊 People invited so far: <b>{referrals}</b>\n\n"
        f"💬 Share this message:\n"
        f"<i>I use this free Telegram bot to get daily remote job alerts — no spam, just relevant jobs every morning. Check it out: t.me/{BOT_USERNAME}?start=ref_{chat_id}</i>")

def handle_stop(chat_id):
    db_update(chat_id, {"active": False})
    send(chat_id, "⏸ Alerts paused.\n\nTap below to restart anytime.",
         [[{"text": "▶️ Restart Alerts", "callback_data": "setup_start"}]])

def step1_category(chat_id, msg_id):
    edit(chat_id, msg_id,
         "⚙️ <b>Step 1 of 4 — Job Category</b>\n\nWhat type of jobs are you looking for?",
         kb_category())

def step2_seniority(chat_id, msg_id, category, cb_id):
    answer(cb_id, f"✅ {CAT_LABELS.get(category, category)}")
    db_update(chat_id, {"category": category})
    edit(chat_id, msg_id,
         f"✅ Category: {CAT_LABELS.get(category, category)}\n\n"
         f"⚙️ <b>Step 2 of 4 — Seniority Level</b>\n\nWhat level are you targeting?",
         kb_seniority())

def step3_location(chat_id, msg_id, seniority, cb_id):
    answer(cb_id, f"✅ {SEN_LABELS.get(seniority, seniority)}")
    db_update(chat_id, {"seniority": seniority})
    edit(chat_id, msg_id,
         f"✅ Level: {SEN_LABELS.get(seniority, seniority)}\n\n"
         f"⚙️ <b>Step 3 of 4 — Location</b>\n\nWhere are you looking to work?",
         kb_location())

def step4_company_type(chat_id, msg_id, loc_key, cb_id):
    loc_map = {
        "remote": ("Remote", True), "usa": ("USA", False), "uk": ("UK", False),
        "india": ("India", False), "nigeria": ("Nigeria", False),
        "japan": ("Japan", False), "china": ("China", False),
        "sea": ("Southeast Asia", False), "me": ("Middle East", False),
        "europe": ("Europe", False), "worldwide": ("Worldwide", False),
    }
    loc_name, remote_only = loc_map.get(loc_key, ("Worldwide", False))
    answer(cb_id, f"✅ {LOC_LABELS.get(loc_key, loc_key)}")
    db_update(chat_id, {"location": loc_name, "location_key": loc_key, "remote_only": remote_only})
    edit(chat_id, msg_id,
         f"✅ Location: {LOC_LABELS.get(loc_key, loc_key)}\n\n"
         f"⚙️ <b>Step 4 of 4 — Company Type</b>\n\nWhat kind of company do you prefer?",
         kb_company_type())

def fmt_job(job):
    from api.jobs import fmt_date
    date_label = f"\n📅 {fmt_date(job['date'])}" if job.get("date") else ""
    loc_label = f"\n📍 {job['location']}" if job.get("location") and job["location"].lower() != "remote" else ""
    funding = f"\n💸 {job['funding']}" if job.get("funding") else ""
    startup = "\n🚀 Early-stage startup" if job.get("company_type") == "startup" and not job.get("funding") else ""
    return (
        f"💼 <b>{job['title']}</b>\n"
        f"🏢 {job['company'] or 'Unknown'}"
        f"{loc_label}{funding}{startup}{date_label}\n"
        f"🔗 <a href='{job['url']}'>Apply Now</a>\n"
        f"📌 via {job['source']}"
    )

def send_jobs_now(chat_id, user, show_button=True):
    try:
        from api.jobs import get_all_jobs, matches_user, score
        send(chat_id, "🔍 Searching for matching jobs...")
        all_jobs = get_all_jobs()
        keywords = user.get("keywords", "")
        sent_ids = get_sent_ids(chat_id)
        matched = [j for j in all_jobs
                   if matches_user(j, user) and j["_id"] not in sent_ids]
        matched.sort(key=lambda j: score(j["title"], keywords), reverse=True)
        matched = matched[:10]

        if not matched:
            send(chat_id,
                "📭 <b>No new jobs found today.</b>\n\n"
                "All matching jobs have already been sent. "
                "Check back tomorrow for fresh listings or broaden your preferences.",
                [[{"text": "⚙️ Change Preferences", "callback_data": "setup_start"},
                  {"text": "🔑 Update Keywords", "callback_data": "add_keywords"}]]
            )
            return

        sources = list({j["source"] for j in matched})
        send(chat_id, f"🔍 <b>{len(matched)} new jobs matching your profile</b>\nSources: {', '.join(sources)}")

        new_ids = []
        for job in matched:
            send(chat_id, fmt_job(job))
            new_ids.append(job["_id"])

        mark_sent(chat_id, new_ids)

        if show_button:
            send(chat_id,
                f"✅ <b>That's all for now.</b>\n\nNext batch arrives tomorrow at 9am UTC.",
                kb_after_jobs())

    except Exception as e:
        print(f"send_jobs_now error: {e}")
        send(chat_id, "Something went wrong. Try again in a moment.")

def finish_setup(chat_id, msg_id, ctype, cb_id):
    answer(cb_id, f"✅ {CTYPE_LABELS.get(ctype, ctype)}")
    db_update(chat_id, {"company_type": ctype, "active": True, "setup_complete": True})
    user = db_get(chat_id)
    invite_link = f"t.me/{BOT_USERNAME}?start=ref_{chat_id}"
    send(chat_id,
        f"🎉 <b>All set! Your daily alerts are live.</b>\n\n"
        f"📂 {CAT_LABELS.get(user.get('category','all'),'All Categories')}\n"
        f"🎯 {SEN_LABELS.get(user.get('seniority','all'),'All Levels')}\n"
        f"📍 {LOC_LABELS.get(user.get('location_key','worldwide'),'Worldwide')}\n"
        f"🏢 {CTYPE_LABELS.get(ctype,'Any')}\n\n"
        f"💡 Add keywords: <code>/keywords ambassador, kol manager, discord mod</code>\n\n"
        f"👥 <b>Share with friends:</b>\n<code>{invite_link}</code>",
        [[{"text": "📋 My Preferences", "callback_data": "status"},
          {"text": "👥 Invite Friends", "callback_data": "invite"}]]
    )
    send_jobs_now(chat_id, user)

def handle_keywords(chat_id, text):
    keywords = text.replace("/keywords", "").strip().lstrip(",").strip()
    if not keywords:
        db_update(chat_id, {"awaiting_keywords": True})
        send(chat_id,
             "✏️ <b>Add Keywords</b>\n\n"
             "Type your keywords below and send:\n\n"
             "<b>Examples:</b>\n"
             "• <code>moderator, community manager</code>\n"
             "• <code>ambassador, kol manager, discord mod</code>\n"
             "• <code>zealy, galxe, telegram moderator</code>")
        return
    db_update(chat_id, {"keywords": keywords, "awaiting_keywords": False})
    send(chat_id, f"✅ Keywords saved: <b>{keywords}</b>")
    user = db_get(chat_id)
    send_jobs_now(chat_id, user)

def process_update(update):
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        username = msg.get("from", {}).get("username", "")
        text = msg.get("text", "")

        # Handle keyword reply state
        if text and not text.startswith("/"):
            user = db_get(chat_id)
            if user.get("awaiting_keywords"):
                db_update(chat_id, {"keywords": text.strip(), "awaiting_keywords": False})
                send(chat_id, f"✅ Keywords saved: <b>{text.strip()}</b>")
                user = db_get(chat_id)
                send_jobs_now(chat_id, user)
                return

        if text.startswith("/start"):
            # Extract referral code if present
            parts = text.split(" ", 1)
            ref_code = parts[1].strip() if len(parts) > 1 else None
            handle_start(chat_id, username, ref_code)
        elif text.startswith("/invite") or text.startswith("/refer"):
            handle_invite(chat_id)
        elif text.startswith("/keywords"):
            handle_keywords(chat_id, text)
        elif text.startswith("/stop"):
            handle_stop(chat_id)
        elif text.startswith("/status"):
            handle_status(chat_id)
        elif text.startswith("/setup"):
            send(chat_id, "Let's update your preferences:", kb_main())
        elif text.startswith("/find"):
            user = db_get(chat_id)
            if user.get("setup_complete"):
                send_jobs_now(chat_id, user)
            else:
                send(chat_id, "Please set up your preferences first.", kb_main())
        elif text.startswith("/help"):
            send(chat_id,
                "📖 <b>Remote Radar Commands</b>\n\n"
                "/start — Welcome & setup\n"
                "/setup — Change preferences\n"
                "/keywords — Add specific role keywords\n"
                "/find — Find jobs right now\n"
                "/invite — Get your invite link\n"
                "/status — View your preferences\n"
                "/stop — Pause alerts\n"
                "/help — This message")

    elif "callback_query" in update:
        cb = update["callback_query"]
        chat_id = cb["from"]["id"]
        username = cb["from"].get("username", "")
        msg_id = cb["message"]["message_id"]
        data = cb.get("data", "")
        cb_id = cb["id"]

        if not db_get(chat_id):
            db_set(chat_id, {"username": username, "active": False, "setup_complete": False})

        if data == "setup_start":
            answer(cb_id)
            step1_category(chat_id, msg_id)
        elif data == "find_jobs":
            answer(cb_id, "Searching...")
            user = db_get(chat_id)
            send_jobs_now(chat_id, user)
        elif data == "invite":
            answer(cb_id)
            handle_invite(chat_id)
        elif data == "add_keywords":
            answer(cb_id)
            db_update(chat_id, {"awaiting_keywords": True})
            send(chat_id,
                 "✏️ <b>Add Keywords</b>\n\n"
                 "Type your keywords below and send:\n\n"
                 "<b>Examples:</b>\n"
                 "• <code>moderator, community manager</code>\n"
                 "• <code>ambassador, kol manager, discord mod</code>\n"
                 "• <code>zealy, galxe, telegram moderator</code>")
        elif data == "status":
            answer(cb_id)
            handle_status(chat_id)
        elif data == "stop":
            answer(cb_id)
            handle_stop(chat_id)
        elif data.startswith("cat_"):
            step2_seniority(chat_id, msg_id, data.replace("cat_",""), cb_id)
        elif data.startswith("sen_"):
            step3_location(chat_id, msg_id, data.replace("sen_",""), cb_id)
        elif data.startswith("loc_"):
            step4_company_type(chat_id, msg_id, data.replace("loc_",""), cb_id)
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

    def log_message(self, format, *args):
        pass
