"""
Telegram Webhook Handler — Public Bot
Handles /start, /setup, /stop, /status commands.
Stores user preferences in Supabase.
"""
import os, json, requests
from http.server import BaseHTTPRequestHandler

BOT_TOKEN  = os.environ.get("JOB_BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

WELCOME = """👋 Welcome to <b>Remote Radar</b>!

I send you daily alerts for remote jobs that match your preferences — for free.

🔍 Jobs from 6+ sources updated daily
🌍 Remote jobs worldwide
⚡ Delivered straight to Telegram

Tap <b>Setup Alerts</b> to get started 👇"""

CATEGORIES = {
    "community": "Community & Social Media",
    "marketing": "Marketing & Growth",
    "support": "Customer Support",
    "web3": "Web3 & Crypto",
    "all": "All Remote Jobs",
}

# ── Supabase helpers ──────────────────────────────────────────────────────────

def db_get(chat_id):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?chat_id=eq.{chat_id}&select=*",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
        timeout=10
    )
    data = r.json()
    return data[0] if data else None

def db_upsert(chat_id, data):
    data["chat_id"] = chat_id
    requests.post(
        f"{SUPABASE_URL}/rest/v1/users",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        },
        json=data,
        timeout=10
    )

def db_delete(chat_id):
    requests.delete(
        f"{SUPABASE_URL}/rest/v1/users?chat_id=eq.{chat_id}",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
        timeout=10
    )

# ── Telegram helpers ──────────────────────────────────────────────────────────

def send(chat_id, text, keyboard=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    requests.post(f"{TG_API}/sendMessage", json=payload, timeout=10)

def answer_callback(callback_id, text=""):
    requests.post(f"{TG_API}/answerCallbackQuery",
                  json={"callback_query_id": callback_id, "text": text}, timeout=5)

def edit_message(chat_id, message_id, text, keyboard=None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    requests.post(f"{TG_API}/editMessageText", json=payload, timeout=10)

# ── Keyboards ─────────────────────────────────────────────────────────────────

def main_keyboard():
    return [
        [{"text": "⚙️ Setup My Alerts", "callback_data": "setup_start"}],
        [{"text": "📋 My Preferences", "callback_data": "status"},
         {"text": "⏹ Stop Alerts", "callback_data": "stop"}],
    ]

def category_keyboard():
    return [
        [{"text": "🌐 Community & Social Media", "callback_data": "cat_community"}],
        [{"text": "📣 Marketing & Growth", "callback_data": "cat_marketing"}],
        [{"text": "💬 Customer Support", "callback_data": "cat_support"}],
        [{"text": "🔗 Web3 & Crypto", "callback_data": "cat_web3"}],
        [{"text": "🌍 All Remote Jobs", "callback_data": "cat_all"}],
    ]

def location_keyboard():
    return [
        [{"text": "🌍 Remote Only", "callback_data": "loc_remote"}],
        [{"text": "🇺🇸 USA", "callback_data": "loc_usa"},
         {"text": "🇬🇧 UK", "callback_data": "loc_uk"}],
        [{"text": "🇮🇳 India", "callback_data": "loc_india"},
         {"text": "🇪🇺 Europe", "callback_data": "loc_europe"}],
        [{"text": "🌐 Worldwide", "callback_data": "loc_worldwide"}],
    ]

# ── Category keyword mapping ───────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "community": "community manager,community lead,discord moderator,telegram moderator,moderator,community mod,community growth,ambassador",
    "marketing": "marketing manager,marketing lead,growth manager,growth marketing,kol manager,influencer marketing,partnerships manager,social media manager,content creator,digital marketing",
    "support": "customer support,customer success,support specialist,support agent,help desk,live chat support",
    "web3": "web3,crypto,blockchain,defi,dao,nft,community manager,marketing,ambassador,support",
    "all": "community,marketing,support,social media,ambassador,growth,partnerships,customer success",
}

# ── Command handlers ───────────────────────────────────────────────────────────

def handle_start(chat_id, username):
    db_upsert(chat_id, {
        "username": username or "",
        "active": False,
        "setup_complete": False,
    })
    send(chat_id, WELCOME, main_keyboard())

def handle_status(chat_id):
    user = db_get(chat_id)
    if not user or not user.get("setup_complete"):
        send(chat_id, "You haven't set up your alerts yet.", main_keyboard())
        return
    category = user.get("category", "all")
    location = user.get("location", "Remote")
    active = "✅ Active" if user.get("active") else "⏸ Paused"
    send(chat_id,
        f"📋 <b>Your Alert Preferences</b>\n\n"
        f"Category: {CATEGORIES.get(category, category)}\n"
        f"Location: {location}\n"
        f"Status: {active}\n\n"
        f"You receive alerts daily at 9am UTC.",
        [[{"text": "✏️ Change Preferences", "callback_data": "setup_start"},
          {"text": "⏹ Stop Alerts", "callback_data": "stop"}]]
    )

def handle_stop(chat_id):
    db_upsert(chat_id, {"active": False})
    send(chat_id,
        "⏹ Alerts paused. You won't receive any more job alerts.\n\n"
        "Tap below to restart anytime.",
        [[{"text": "▶️ Restart Alerts", "callback_data": "setup_start"}]]
    )

def handle_setup_category(chat_id, message_id):
    edit_message(chat_id, message_id,
        "🎯 <b>Step 1 of 2 — Job Category</b>\n\nWhat type of remote jobs are you looking for?",
        category_keyboard()
    )

def handle_category_selected(chat_id, message_id, category, callback_id):
    answer_callback(callback_id, f"Selected: {CATEGORIES.get(category, category)}")
    db_upsert(chat_id, {"category": category, "keywords": CATEGORY_KEYWORDS.get(category, "")})
    edit_message(chat_id, message_id,
        f"✅ Category: <b>{CATEGORIES.get(category, category)}</b>\n\n"
        "📍 <b>Step 2 of 2 — Location</b>\n\nWhere are you looking to work?",
        location_keyboard()
    )

def handle_location_selected(chat_id, message_id, location, callback_id):
    loc_map = {
        "remote": "Remote", "usa": "USA", "uk": "UK",
        "india": "India", "europe": "Europe", "worldwide": "Worldwide"
    }
    loc_name = loc_map.get(location, "Remote")
    remote_only = location == "remote"
    answer_callback(callback_id, f"Selected: {loc_name}")
    db_upsert(chat_id, {
        "location": loc_name,
        "remote_only": remote_only,
        "active": True,
        "setup_complete": True,
    })
    send(chat_id,
        f"🎉 <b>You're all set!</b>\n\n"
        f"You'll receive daily job alerts for:\n"
        f"📂 {CATEGORIES.get(db_get(chat_id).get('category','all'), 'All Jobs')}\n"
        f"📍 {loc_name}\n\n"
        f"First alerts arrive tomorrow at 9am UTC.\n"
        f"Share this bot with friends who need remote jobs! 👇\n\n"
        f"<b>t.me/{get_bot_username()}</b>",
        [[{"text": "📋 View My Preferences", "callback_data": "status"}]]
    )

def get_bot_username():
    try:
        r = requests.get(f"{TG_API}/getMe", timeout=5)
        return r.json().get("result", {}).get("username", "RemoteRadarBot")
    except Exception:
        return "RemoteRadarBot"

# ── Main webhook handler ───────────────────────────────────────────────────────

def process_update(update):
    # Handle regular messages
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        username = msg.get("from", {}).get("username", "")
        text = msg.get("text", "")

        if text.startswith("/start"):
            handle_start(chat_id, username)
        elif text.startswith("/setup"):
            send(chat_id, "Let's update your preferences:", main_keyboard())
        elif text.startswith("/stop"):
            handle_stop(chat_id)
        elif text.startswith("/status"):
            handle_status(chat_id)
        elif text.startswith("/help"):
            send(chat_id,
                "📖 <b>Remote Radar Commands</b>\n\n"
                "/start — Welcome & setup\n"
                "/setup — Change preferences\n"
                "/status — View your preferences\n"
                "/stop — Pause alerts\n"
                "/help — This message"
            )

    # Handle button presses
    elif "callback_query" in update:
        cb = update["callback_query"]
        chat_id = cb["from"]["id"]
        message_id = cb["message"]["message_id"]
        data = cb.get("data", "")
        callback_id = cb["id"]

        if data == "setup_start":
            handle_setup_category(chat_id, message_id)
        elif data == "status":
            answer_callback(callback_id)
            handle_status(chat_id)
        elif data == "stop":
            answer_callback(callback_id)
            handle_stop(chat_id)
        elif data.startswith("cat_"):
            category = data.replace("cat_", "")
            handle_category_selected(chat_id, message_id, category, callback_id)
        elif data.startswith("loc_"):
            location = data.replace("loc_", "")
            handle_location_selected(chat_id, message_id, location, callback_id)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            update = json.loads(body)
            process_update(update)
        except Exception as e:
            print(f"Webhook error: {e}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Remote Radar webhook is running.")

    def log_message(self, format, *args):
        pass
