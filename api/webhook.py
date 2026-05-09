"""
Remote Radar — Public Telegram Bot Webhook
Full setup flow: category, seniority, location, keywords, company type
"""
import os, json, requests
from http.server import BaseHTTPRequestHandler

BOT_TOKEN    = os.environ.get("JOB_BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
TG_API       = f"https://api.telegram.org/bot{BOT_TOKEN}"

WELCOME = """👋 <b>Welcome to Remote Radar!</b>

I find remote jobs worldwide and send alerts straight to your Telegram — daily, free, forever.

🌍 Jobs from 9 sources globally
📂 Every category — Tech, Marketing, Sales, Finance, Executive & more
⚡ Personalised to your exact preferences

Let's set up your alerts in 4 quick steps 👇"""

# ── Supabase ──────────────────────────────────────────────────────────────────

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

# ── Telegram helpers ──────────────────────────────────────────────────────────

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

# ── Step keyboards ────────────────────────────────────────────────────────────

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

# ── Category labels ───────────────────────────────────────────────────────────

CAT_LABELS = {
    "tech": "💻 Tech & Engineering",
    "product": "📦 Product Management",
    "design": "🎨 Design & Creative",
    "marketing": "📣 Marketing & Growth",
    "community": "🌐 Community & Social Media",
    "support": "💬 Customer Support",
    "sales": "💼 Sales & Business Dev",
    "finance": "💰 Finance & Accounting",
    "operations": "⚙️ Operations & HR",
    "executive": "👔 Executive",
    "web3": "🔗 Web3 & Crypto",
    "all": "🌍 All Categories",
}

SEN_LABELS = {
    "entry": "🌱 Entry Level",
    "mid": "📈 Mid Level",
    "senior": "⭐ Senior",
    "manager": "👥 Manager / Lead",
    "director": "🏆 Director / VP",
    "executive": "👑 C-Suite",
    "all": "🌍 All Levels",
}

LOC_LABELS = {
    "remote": "🌍 Remote Only",
    "usa": "🇺🇸 USA",
    "uk": "🇬🇧 UK",
    "india": "🇮🇳 India",
    "nigeria": "🇳🇬 Nigeria",
    "japan": "🇯🇵 Japan",
    "china": "🇨🇳 China",
    "sea": "🌏 SE Asia",
    "me": "🕌 Middle East",
    "europe": "🇪🇺 Europe",
    "worldwide": "🌐 Worldwide",
}

CTYPE_LABELS = {
    "startup": "🚀 Startups",
    "established": "🏢 Established",
    "any": "🌍 Any",
}

# ── Handlers ──────────────────────────────────────────────────────────────────

def handle_start(chat_id, username):
    existing = db_get(chat_id)
    if not existing:
        db_set(chat_id, {"username": username or "", "active": False, "setup_complete": False})
    send(chat_id, WELCOME, kb_main())

def handle_status(chat_id):
    user = db_get(chat_id)
    if not user or not user.get("setup_complete"):
        send(chat_id, "You haven't set up alerts yet. Tap below to get started.", kb_main())
        return
    status = "✅ Active" if user.get("active") else "⏸ Paused"
    kws = user.get("keywords","") or "None set"
    send(chat_id,
        f"📋 <b>Your Alert Preferences</b>\n\n"
        f"📂 Category: {CAT_LABELS.get(user.get('category','all'), 'All')}\n"
        f"🎯 Level: {SEN_LABELS.get(user.get('seniority','all'), 'All')}\n"
        f"📍 Location: {LOC_LABELS.get(user.get('location_key','worldwide'), 'Worldwide')}\n"
        f"🏢 Company: {CTYPE_LABELS.get(user.get('company_type','any'), 'Any')}\n"
        f"🔑 Keywords: {kws}\n"
        f"📡 Status: {status}\n\n"
        f"Alerts arrive daily at 9am UTC.",
        [[{"text": "✏️ Change Preferences", "callback_data": "setup_start"},
          {"text": "⏹ Pause", "callback_data": "stop"}]]
    )

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
        "remote": ("Remote", True),
        "usa": ("USA", False),
        "uk": ("UK", False),
        "india": ("India", False),
        "nigeria": ("Nigeria", False),
        "japan": ("Japan", False),
        "china": ("China", False),
        "sea": ("Southeast Asia", False),
        "me": ("Middle East", False),
        "europe": ("Europe", False),
        "worldwide": ("Worldwide", False),
    }
    loc_name, remote_only = loc_map.get(loc_key, ("Worldwide", False))
    answer(cb_id, f"✅ {LOC_LABELS.get(loc_key, loc_key)}")
    db_update(chat_id, {"location": loc_name, "location_key": loc_key, "remote_only": remote_only})
    edit(chat_id, msg_id,
         f"✅ Location: {LOC_LABELS.get(loc_key, loc_key)}\n\n"
         f"⚙️ <b>Step 4 of 4 — Company Type</b>\n\nWhat kind of company do you prefer?",
         kb_company_type())

def finish_setup(chat_id, msg_id, ctype, cb_id):
    answer(cb_id, f"✅ {CTYPE_LABELS.get(ctype, ctype)}")
    db_update(chat_id, {
        "company_type": ctype,
        "active": True,
        "setup_complete": True,
    })
    user = db_get(chat_id)
    send(chat_id,
        f"🎉 <b>All set! Your daily alerts are live.</b>\n\n"
        f"📂 {CAT_LABELS.get(user.get('category','all'),'All Categories')}\n"
        f"🎯 {SEN_LABELS.get(user.get('seniority','all'),'All Levels')}\n"
        f"📍 {LOC_LABELS.get(user.get('location_key','worldwide'),'Worldwide')}\n"
        f"🏢 {CTYPE_LABELS.get(ctype,'Any')}\n\n"
        f"You'll get your first alerts tomorrow at 9am UTC.\n\n"
        f"💡 <b>Tip:</b> Add specific keywords by sending /keywords\n"
        f"Example: <code>/keywords community manager, web3, discord</code>\n\n"
        f"Share with friends who need remote jobs! 🚀",
        [[{"text": "📋 View My Preferences", "callback_data": "status"}]]
    )

def handle_keywords(chat_id, text):
    keywords = text.replace("/keywords", "").strip()
    if not keywords:
        send(chat_id,
             "Send your keywords like this:\n\n"
             "<code>/keywords community manager, web3, discord</code>\n\n"
             "Jobs matching any of these will be included in your alerts.")
        return
    db_update(chat_id, {"keywords": keywords})
    send(chat_id, f"✅ Keywords saved: <b>{keywords}</b>\n\nThese will be used to filter your job alerts.")

# ── Main processor ────────────────────────────────────────────────────────────

def process_update(update):
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        username = msg.get("from", {}).get("username", "")
        text = msg.get("text", "")

        if text.startswith("/start"):
            handle_start(chat_id, username)
        elif text.startswith("/keywords"):
            handle_keywords(chat_id, text)
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
                "/keywords web3, marketing — Set custom keywords\n"
                "/status — View your preferences\n"
                "/stop — Pause alerts\n"
                "/help — This message\n\n"
                "🌍 Covering jobs worldwide across all categories.")

    elif "callback_query" in update:
        cb = update["callback_query"]
        chat_id = cb["from"]["id"]
        username = cb["from"].get("username", "")
        msg_id = cb["message"]["message_id"]
        data = cb.get("data", "")
        cb_id = cb["id"]

        # Ensure user exists
        if not db_get(chat_id):
            db_set(chat_id, {"username": username, "active": False, "setup_complete": False})

        if data == "setup_start":
            answer(cb_id)
            step1_category(chat_id, msg_id)
        elif data == "status":
            answer(cb_id)
            handle_status(chat_id)
        elif data == "stop":
            answer(cb_id)
            handle_stop(chat_id)
        elif data.startswith("cat_"):
            category = data.replace("cat_", "")
            step2_seniority(chat_id, msg_id, category, cb_id)
        elif data.startswith("sen_"):
            seniority = data.replace("sen_", "")
            step3_location(chat_id, msg_id, seniority, cb_id)
        elif data.startswith("loc_"):
            loc_key = data.replace("loc_", "")
            step4_company_type(chat_id, msg_id, loc_key, cb_id)
        elif data.startswith("ctype_"):
            ctype = data.replace("ctype_", "")
            finish_setup(chat_id, msg_id, ctype, cb_id)


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
