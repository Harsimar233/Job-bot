"""
Remote Radar — Public Telegram Bot Webhook
Features: Setup flow, job alerts, /find, /apply tracker, /watch, /market, /cover, /invite
"""
import os, json, re, requests
from http.server import BaseHTTPRequestHandler

BOT_TOKEN  = os.environ.get("JOB_BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
BOT_USERNAME = "RemoteDailyJobBot"

# ── Supabase helpers ──────────────────────────────────────────────────────────

def _sb(method, path, body=None, params=None):
    hdrs = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json", "Prefer": "return=representation"}
    url = SUPABASE_URL.rstrip("/") + "/rest/v1/" + path
    try:
        r = getattr(requests, method)(url, headers=hdrs, json=body, params=params, timeout=10)
        if r.status_code in (200, 201):
            d = r.json()
            return d[0] if isinstance(d, list) and d else d
        return None
    except Exception:
        return None

def db_get(chat_id):
    return _sb("get", f"users?chat_id=eq.{chat_id}") or {}

def db_set(chat_id, data):
    data["chat_id"] = chat_id
    _sb("post", "users", data)

def db_update(chat_id, data):
    _sb("patch", f"users?chat_id=eq.{chat_id}", data)

def db_upsert(chat_id, data):
    data["chat_id"] = chat_id
    _sb("post", "users", data, params={"on_conflict": "chat_id"})

def was_sent(chat_id, job_id):
    r = _sb("get", f"sent_jobs?chat_id=eq.{chat_id}&job_id=eq.{job_id}")
    return bool(r)

def mark_sent(chat_id, job_id):
    _sb("post", "sent_jobs", {"chat_id": chat_id, "job_id": job_id})

def log_application(chat_id, job_title, company, status, url=""):
    _sb("post", "applications", {
        "chat_id": chat_id, "job_title": job_title,
        "company": company, "status": status, "url": url
    })

def get_applications(chat_id):
    hdrs = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    url = SUPABASE_URL.rstrip("/") + f"/rest/v1/applications?chat_id=eq.{chat_id}&order=created_at.desc"
    try:
        r = requests.get(url, headers=hdrs, timeout=10)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []

def get_watchlist(chat_id):
    hdrs = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    url = SUPABASE_URL.rstrip("/") + f"/rest/v1/watchlist?chat_id=eq.{chat_id}"
    try:
        r = requests.get(url, headers=hdrs, timeout=10)
        return [w["company"].lower() for w in (r.json() if r.status_code == 200 else [])]
    except Exception:
        return []

def add_watchlist(chat_id, company):
    _sb("post", "watchlist", {"chat_id": chat_id, "company": company.lower()})

def remove_watchlist(chat_id, company):
    hdrs = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    url = SUPABASE_URL.rstrip("/") + f"/rest/v1/watchlist?chat_id=eq.{chat_id}&company=eq.{company.lower()}"
    requests.delete(url, headers=hdrs, timeout=10)

def increment_referrals(referrer_id):
    r = db_get(referrer_id)
    if r:
        db_update(referrer_id, {"referrals": (r.get("referrals") or 0) + 1})

# ── Telegram helpers ──────────────────────────────────────────────────────────

def send(chat_id, text, buttons=None):
    payload = {
        "chat_id": chat_id, "text": text[:4096],
        "parse_mode": "HTML", "disable_web_page_preview": True,
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    try:
        requests.post(f"{TG_API}/sendMessage", json=payload, timeout=10)
    except Exception:
        pass

def answer(callback_id, text="✅"):
    try:
        requests.post(f"{TG_API}/answerCallbackQuery",
                      json={"callback_query_id": callback_id, "text": text}, timeout=5)
    except Exception:
        pass

def edit(chat_id, msg_id, text, buttons=None):
    payload = {"chat_id": chat_id, "message_id": msg_id,
               "text": text[:4096], "parse_mode": "HTML"}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    try:
        requests.post(f"{TG_API}/editMessageText", json=payload, timeout=10)
    except Exception:
        pass

# ── Labels & setup flow ───────────────────────────────────────────────────────

CAT_LABELS = {
    "community": "👥 Community & Social", "marketing": "📣 Marketing & Growth",
    "support": "🎧 Customer Support", "tech": "💻 Tech & Engineering",
    "product": "📱 Product", "design": "🎨 Design & Creative",
    "sales": "💼 Sales & BD", "finance": "💰 Finance & Accounting",
    "operations": "⚙️ Operations & HR", "executive": "🏆 Executive (C-Suite/VP)",
    "web3": "🌐 Web3 & Crypto", "all": "🌍 All Categories",
}
SEN_LABELS = {
    "entry": "🌱 Entry Level", "mid": "🔧 Mid Level", "senior": "⭐ Senior",
    "manager": "👔 Manager", "director": "📊 Director", "csuite": "👑 C-Suite/VP", "all": "🌍 All Levels",
}
LOC_LABELS = {
    "remote": "🌐 Remote Only", "usa": "🇺🇸 USA", "uk": "🇬🇧 UK",
    "india": "🇮🇳 India", "europe": "🇪🇺 Europe", "nigeria": "🇳🇬 Nigeria",
    "japan": "🇯🇵 Japan", "sea": "🌏 SE Asia", "middleeast": "🇦🇪 Middle East",
    "worldwide": "🌐 Worldwide",
}
CTYPE_LABELS = {
    "startup": "🚀 Startups & Early Stage", "established": "🏢 Established Companies",
    "any": "🌍 Any",
}

WELCOME = """👋 <b>Welcome to Remote Radar!</b>

🎯 Set your preferences <b>once</b>. Get fresh job alerts every morning — automatically, free, forever.

🌍 Jobs from <b>15+ sources globally</b>
📂 Every category — Community, Marketing, Support, Tech, Finance, Executive & more
⏰ <b>Daily alerts at 9am UTC</b> — no manual searching ever again
🔥 Hot jobs flagged when posted in last 24 hours
💰 Salary info included where available

💡 After setup, use /keywords to target specific roles:
<code>ambassador, kol manager, discord moderator, zealy</code>

Let's set up in 4 quick steps 👇

<i>Made by <a href="https://t.me/Harsimarhs">@Harsimarhs</a> · Reach out for any queries</i>"""


def kb_main():
    return [[{"text": "⚡ Setup My Alerts", "callback_data": "setup_start"}]]

def kb_categories():
    rows = []
    items = list(CAT_LABELS.items())
    for i in range(0, len(items), 2):
        row = [{"text": items[i][1], "callback_data": f"cat_{items[i][0]}"}]
        if i+1 < len(items):
            row.append({"text": items[i+1][1], "callback_data": f"cat_{items[i+1][0]}"})
        rows.append(row)
    return rows

def kb_seniority():
    rows = []
    items = list(SEN_LABELS.items())
    for i in range(0, len(items), 2):
        row = [{"text": items[i][1], "callback_data": f"sen_{items[i][0]}"}]
        if i+1 < len(items):
            row.append({"text": items[i+1][1], "callback_data": f"sen_{items[i+1][0]}"})
        rows.append(row)
    return rows

def kb_locations():
    rows = []
    items = list(LOC_LABELS.items())
    for i in range(0, len(items), 2):
        row = [{"text": items[i][1], "callback_data": f"loc_{items[i][0]}"}]
        if i+1 < len(items):
            row.append({"text": items[i+1][1], "callback_data": f"loc_{items[i+1][0]}"})
        rows.append(row)
    return rows

def kb_ctype():
    return [[{"text": v, "callback_data": f"ctype_{k}"} for k, v in CTYPE_LABELS.items()]]

def kb_post_setup():
    return [
        [{"text": "🔍 Find Jobs Now", "callback_data": "find_now"},
         {"text": "📋 My Preferences", "callback_data": "status"}],
        [{"text": "👥 Invite Friends", "callback_data": "invite_link"}],
    ]

def kb_find_more():
    return [[{"text": "🔍 Find More Jobs", "callback_data": "find_now"}]]


# ── Job formatting ────────────────────────────────────────────────────────────

def format_job(job, show_hot=True):
    hot = "🔥 " if (show_hot and job.get("hot")) else ""
    title = f"{hot}<b>{job['title']}</b>"
    company = f"🏢 {job['company']}" if job.get("company") else ""
    loc = f"\n📍 {job['location']}" if job.get("location") and job["location"].lower() not in ("remote", "") else ""
    sal = f"\n💰 {job['salary']}" if job.get("salary") else ""
    fund = f"\n💸 Funding: {job['funding']}" if job.get("funding") else ""
    visa = "\n✈️ Visa sponsorship" if job.get("visa") else ""
    date = f"\n📅 {fmt_date_display(job['date'])}" if job.get("date") else ""
    src = f"📌 {job['source']}"
    url = job.get("url", "")

    lines = [f"💼 {title}"]
    if company: lines.append(company)
    if loc: lines.append(loc)
    if sal: lines.append(sal)
    if fund: lines.append(fund)
    if visa: lines.append(visa)
    if date: lines.append(date)
    lines.append(f"🔗 <a href='{url}'>Apply Now</a>")
    lines.append(src)
    return "\n".join(lines)


def fmt_date_display(date_str):
    from datetime import datetime
    if not date_str: return ""
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return dt.strftime("%d %b %Y")
    except Exception:
        return date_str[:10]


# ── Handlers ──────────────────────────────────────────────────────────────────

def handle_start(chat_id, username, ref=None):
    # Track referral
    if ref and ref.startswith("ref_"):
        try:
            referrer_id = int(ref.replace("ref_", ""))
            if referrer_id != chat_id:
                increment_referrals(referrer_id)
                send(referrer_id, f"🎉 Someone joined using your invite link! You've referred another person. Keep sharing!")
        except Exception:
            pass

    db_upsert(chat_id, {
        "username": username or "",
        "active": False, "setup_complete": False,
        "category": "all", "seniority": "all",
        "keywords": "", "location": "Worldwide",
        "location_key": "worldwide", "remote_only": False,
        "company_type": "any", "awaiting_keywords": False,
        "referred_by": None,
    })
    send(chat_id, WELCOME, kb_main())


def handle_setup_start(chat_id, msg_id, cb_id):
    answer(cb_id, "Let's set up your alerts!")
    edit(chat_id, msg_id,
         "⚙️ <b>Step 1 of 4 — Job Category</b>\n\nWhat type of jobs are you looking for?",
         kb_categories())


def handle_category(chat_id, msg_id, cat, cb_id):
    answer(cb_id, f"✅ {CAT_LABELS.get(cat, cat)}")
    db_update(chat_id, {"category": cat})
    edit(chat_id, msg_id,
         f"✅ Category: {CAT_LABELS.get(cat, cat)}\n\n⚙️ <b>Step 2 of 4 — Seniority Level</b>\n\nWhat level are you targeting?",
         kb_seniority())


def handle_seniority(chat_id, msg_id, sen, cb_id):
    answer(cb_id, f"✅ {SEN_LABELS.get(sen, sen)}")
    db_update(chat_id, {"seniority": sen})
    edit(chat_id, msg_id,
         f"✅ Seniority: {SEN_LABELS.get(sen, sen)}\n\n⚙️ <b>Step 3 of 4 — Location</b>\n\nWhere are you looking to work?",
         kb_locations())


def handle_location(chat_id, msg_id, loc, cb_id):
    answer(cb_id, f"✅ {LOC_LABELS.get(loc, loc)}")
    db_update(chat_id, {"location": LOC_LABELS.get(loc, loc), "location_key": loc})
    edit(chat_id, msg_id,
         f"✅ Location: {LOC_LABELS.get(loc, loc)}\n\n⚙️ <b>Step 4 of 4 — Company Type</b>\n\nWhat kind of company do you prefer?",
         kb_ctype())


def handle_ctype(chat_id, msg_id, ctype, cb_id):
    answer(cb_id, f"✅ {CTYPE_LABELS.get(ctype, ctype)}")
    db_update(chat_id, {"company_type": ctype, "active": True, "setup_complete": True})
    user = db_get(chat_id)

    edit(chat_id, msg_id,
         f"🎉 <b>All set! Your daily alerts are live.</b>\n\n"
         f"📂 {CAT_LABELS.get(user.get('category','all'),'All Categories')}\n"
         f"🎯 {SEN_LABELS.get(user.get('seniority','all'),'All Levels')}\n"
         f"📍 {LOC_LABELS.get(user.get('location_key','worldwide'),'Worldwide')}\n"
         f"🏢 {CTYPE_LABELS.get(ctype,'Any')}\n\n"
         f"⏰ Daily alerts every morning at 9am UTC\n\n"
         f"💡 Tip: Use /keywords to add specific roles:\n"
         f"<code>ambassador, kol manager, discord moderator, zealy, galxe</code>",
         kb_post_setup())

    send_jobs_now(chat_id, user)


def handle_find_now(chat_id, cb_id):
    answer(cb_id, "🔍 Searching...")
    user = db_get(chat_id)
    if not user:
        send(chat_id, "Please /start first to set up your preferences.")
        return
    send_jobs_now(chat_id, user)


def send_jobs_now(chat_id, user):
    try:
        from api.jobs import get_all_jobs, matches_user, score
        all_jobs = get_all_jobs()
        keywords = user.get("keywords", "")
        matched = [j for j in all_jobs if matches_user(j, user) and not was_sent(chat_id, j["id"])]
        matched.sort(key=lambda j: (-score(j["title"], keywords), not j.get("hot")))
        batch = matched[:10]

        if not batch:
            send(chat_id,
                 "✅ <b>You're all caught up!</b>\n\nNo new matching jobs found right now.\n"
                 "Fresh listings arrive daily at 9am UTC.",
                 kb_find_more())
            return

        hot_count = sum(1 for j in batch if j.get("hot"))
        sources = list({j["source"] for j in batch})
        header = f"🔍 <b>{len(batch)} jobs matching your profile</b>"
        if hot_count:
            header += f" · 🔥 {hot_count} hot (last 24h)"
        header += f"\n📡 {', '.join(sources)}"
        send(chat_id, header)

        for job in batch:
            send(chat_id, format_job(job))
            mark_sent(chat_id, job["id"])

        send(chat_id, "That's your batch! New jobs arrive every morning at 9am UTC.",
             kb_find_more())
    except Exception as e:
        print(f"send_jobs_now error: {e}")
        send(chat_id, "⚠️ Couldn't fetch jobs right now. Try again in a moment.", kb_find_more())


def handle_keywords(chat_id, text):
    keywords = text.replace("/keywords", "").strip().lstrip(",").strip()
    if not keywords:
        db_update(chat_id, {"awaiting_keywords": True})
        send(chat_id,
             "✏️ <b>Add Keywords</b>\n\n"
             "Type your keywords below (comma-separated) and send:\n\n"
             "<b>Examples:</b>\n"
             "• <code>moderator, community manager, discord</code>\n"
             "• <code>ambassador, kol manager, telegram mod</code>\n"
             "• <code>zealy, galxe, web3 growth</code>\n"
             "• <code>data engineer, python, remote</code>")
        return
    db_update(chat_id, {"keywords": keywords, "awaiting_keywords": False})
    send(chat_id, f"✅ <b>Keywords saved:</b> {keywords}\n\nFinding matching jobs now...")
    user = db_get(chat_id)
    send_jobs_now(chat_id, user)


def handle_status(chat_id):
    user = db_get(chat_id)
    if not user:
        send(chat_id, "You haven't set up alerts yet. Send /start to begin.")
        return
    ref_count = user.get("referrals", 0)
    kws = user.get("keywords", "") or "None set"
    active = "✅ Active" if user.get("active") else "⏸ Paused"
    invite = f"https://t.me/{BOT_USERNAME}?start=ref_{chat_id}"

    text = (
        f"📋 <b>Your Preferences</b>\n\n"
        f"📂 {CAT_LABELS.get(user.get('category','all'),'All Categories')}\n"
        f"🎯 {SEN_LABELS.get(user.get('seniority','all'),'All Levels')}\n"
        f"📍 {LOC_LABELS.get(user.get('location_key','worldwide'),'Worldwide')}\n"
        f"🏢 {CTYPE_LABELS.get(user.get('company_type','any'),'Any')}\n"
        f"🔑 Keywords: <code>{kws}</code>\n\n"
        f"📡 Status: {active}\n"
        f"👥 Referrals: {ref_count}\n\n"
        f"Use /setup to change preferences\n"
        f"Use /keywords to update keywords\n"
        f"Use /find to get jobs now"
    )
    send(chat_id, text, [
        [{"text": "🔍 Find Jobs Now", "callback_data": "find_now"},
         {"text": "⚙️ Change Setup", "callback_data": "setup_start"}],
        [{"text": "👥 Share Invite Link", "callback_data": "invite_link"}],
    ])


def handle_find_command(chat_id, text):
    """Instant search: /find community manager"""
    query = text.replace("/find", "").strip()
    if not query:
        send(chat_id,
             "🔍 <b>Search Jobs Instantly</b>\n\n"
             "Usage: <code>/find [role]</code>\n\n"
             "Examples:\n"
             "• <code>/find community manager</code>\n"
             "• <code>/find social media manager crypto</code>\n"
             "• <code>/find discord moderator web3</code>\n"
             "• <code>/find marketing manager remote</code>")
        return
    send(chat_id, f"🔍 Searching for <b>{query}</b>...")
    try:
        from api.jobs import get_all_jobs, matches_keywords
        all_jobs = get_all_jobs()
        # Create a fake user with the search query as keywords
        results = [j for j in all_jobs if matches_keywords(j, query)]
        results.sort(key=lambda j: not j.get("hot"))
        results = results[:10]

        if not results:
            send(chat_id, f"No results found for <b>{query}</b> right now. Try different keywords or check back tomorrow.")
            return

        send(chat_id, f"🔍 <b>{len(results)} results for '{query}'</b>")
        for job in results:
            send(chat_id, format_job(job))
    except Exception as e:
        send(chat_id, f"Search failed: {e}")


def handle_market(chat_id):
    """Show market trends — most in-demand roles this week"""
    send(chat_id, "📊 <b>Market Insights</b> — Fetching data...")
    try:
        from api.jobs import get_all_jobs
        jobs = get_all_jobs()

        # Count titles
        from collections import Counter
        words = []
        for j in jobs:
            title = j["title"].lower()
            for kw in ["community manager", "social media", "marketing manager", "customer support",
                       "developer", "engineer", "product manager", "growth", "sales", "designer",
                       "data analyst", "devops", "content", "moderator", "ambassador", "operations"]:
                if kw in title:
                    words.append(kw.title())

        counts = Counter(words).most_common(10)
        top = "\n".join([f"  {i+1}. {role} — {count} openings" for i, (role, count) in enumerate(counts)])

        # Sources breakdown
        src_counts = Counter(j["source"] for j in jobs)
        src_str = " · ".join([f"{src}: {cnt}" for src, cnt in src_counts.most_common(5)])

        hot_count = sum(1 for j in jobs if j.get("hot"))
        salary_count = sum(1 for j in jobs if j.get("salary"))

        send(chat_id,
             f"📊 <b>Market Snapshot — Today</b>\n\n"
             f"📋 Total openings: <b>{len(jobs)}</b>\n"
             f"🔥 Posted last 24h: <b>{hot_count}</b>\n"
             f"💰 With salary info: <b>{salary_count}</b>\n\n"
             f"🏆 <b>Most In-Demand Roles:</b>\n{top}\n\n"
             f"📡 Sources: {src_str}",
             kb_find_more())
    except Exception as e:
        send(chat_id, f"⚠️ Couldn't load market data: {e}")


def handle_apply(chat_id, text):
    """Track job application: /applied Job Title at Company"""
    content = text.replace("/applied", "").strip()
    if not content:
        send(chat_id,
             "✅ <b>Track Your Application</b>\n\n"
             "Usage: <code>/applied [Job Title] at [Company]</code>\n"
             "Example: <code>/applied Community Manager at Coinbase</code>\n\n"
             "Also try:\n"
             "• <code>/interview Community Manager at Coinbase</code>\n"
             "• <code>/rejected Community Manager at Coinbase</code>\n"
             "• <code>/offers</code> — see all your tracked applications")
        return
    # Parse "Title at Company"
    if " at " in content.lower():
        parts = re.split(r'\s+at\s+', content, 1, re.IGNORECASE)
        title, company = parts[0].strip(), parts[1].strip()
    else:
        title, company = content, ""
    log_application(chat_id, title, company, "applied")
    send(chat_id, f"✅ Logged: <b>{title}</b>{f' at {company}' if company else ''}\nStatus: 📤 Applied\n\nUse /offers to see your pipeline.")


def handle_interview(chat_id, text):
    content = text.replace("/interview", "").strip()
    if not content:
        send(chat_id, "Usage: <code>/interview [Job Title] at [Company]</code>")
        return
    if " at " in content.lower():
        parts = re.split(r'\s+at\s+', content, 1, re.IGNORECASE)
        title, company = parts[0].strip(), parts[1].strip()
    else:
        title, company = content, ""
    log_application(chat_id, title, company, "interview")
    send(chat_id, f"🎉 Interview! <b>{title}</b>{f' at {company}' if company else ''}\nGood luck! 🤞")


def handle_rejected(chat_id, text):
    content = text.replace("/rejected", "").strip()
    if not content:
        send(chat_id, "Usage: <code>/rejected [Job Title] at [Company]</code>")
        return
    if " at " in content.lower():
        parts = re.split(r'\s+at\s+', content, 1, re.IGNORECASE)
        title, company = parts[0].strip(), parts[1].strip()
    else:
        title, company = content, ""
    log_application(chat_id, title, company, "rejected")
    send(chat_id, f"😔 Logged as rejected: <b>{title}</b>. Keep going — the right role is coming. 💪")


def handle_offers(chat_id):
    """Show application pipeline"""
    apps = get_applications(chat_id)
    if not apps:
        send(chat_id,
             "📋 <b>Your Application Tracker</b>\n\nNo applications tracked yet.\n\n"
             "Start tracking:\n"
             "• <code>/applied Community Manager at Coinbase</code>\n"
             "• <code>/interview Discord Mod at Uniswap</code>\n"
             "• <code>/rejected Growth Lead at Binance</code>")
        return

    STATUS_ICONS = {"applied": "📤", "interview": "🎤", "rejected": "❌", "offer": "🎉"}
    by_status = {"interview": [], "applied": [], "rejected": []}
    for a in apps:
        s = a.get("status", "applied")
        if s in by_status:
            by_status[s].append(a)

    lines = ["📋 <b>Your Application Pipeline</b>\n"]
    for status, emoji_label in [("interview", "🎤 Interviews"), ("applied", "📤 Applied"), ("rejected", "❌ Rejected")]:
        items = by_status[status]
        if items:
            lines.append(f"\n<b>{emoji_label} ({len(items)})</b>")
            for a in items[:5]:
                co = f" @ {a['company']}" if a.get("company") else ""
                lines.append(f"  • {a['job_title']}{co}")

    lines.append(f"\n<b>Total:</b> {len(apps)} tracked")
    send(chat_id, "\n".join(lines))


def handle_watch(chat_id, text):
    """Watch a company: /watch Coinbase"""
    company = text.replace("/watch", "").strip()
    if not company:
        watchlist = get_watchlist(chat_id)
        if watchlist:
            companies = "\n".join([f"  • {c.title()}" for c in watchlist])
            send(chat_id,
                 f"👁 <b>Your Watchlist</b>\n\n{companies}\n\n"
                 "Usage: <code>/watch [Company]</code> to add\n"
                 "<code>/unwatch [Company]</code> to remove")
        else:
            send(chat_id,
                 "👁 <b>Company Watchlist</b>\n\n"
                 "Get alerted the moment a company posts a new job.\n\n"
                 "Usage: <code>/watch Coinbase</code>\n"
                 "Examples: Coinbase, Binance, OpenAI, Notion, Stripe")
        return
    add_watchlist(chat_id, company)
    send(chat_id,
         f"👁 Now watching <b>{company.title()}</b>\n\n"
         f"You'll be notified the moment they post a new job!")


def handle_unwatch(chat_id, text):
    company = text.replace("/unwatch", "").strip()
    if not company:
        send(chat_id, "Usage: <code>/unwatch [Company]</code>")
        return
    remove_watchlist(chat_id, company)
    send(chat_id, f"✅ Removed <b>{company.title()}</b> from your watchlist.")


def handle_cover(chat_id, text):
    """AI cover letter: /cover [job URL or description]"""
    content = text.replace("/cover", "").strip()
    if not content:
        send(chat_id,
             "📝 <b>AI Cover Letter Generator</b>\n\n"
             "Paste a job URL or job description and I'll write a tailored cover letter.\n\n"
             "Usage:\n"
             "<code>/cover https://jobs.lever.co/coinbase/community-manager</code>\n"
             "or\n"
             "<code>/cover [paste job description here]</code>")
        db_update(chat_id, {"awaiting_cover": True})
        return
    generate_cover_letter(chat_id, content)


def generate_cover_letter(chat_id, content):
    user = db_get(chat_id)
    send(chat_id, "✍️ Writing your cover letter...")
    try:
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not anthropic_key:
            # Fallback template
            send(chat_id,
                 "📝 <b>Cover Letter Template</b>\n\n"
                 "Dear Hiring Manager,\n\n"
                 "I am writing to express my strong interest in this role. With my background in community management, "
                 "social media, and Web3 ecosystems, I am excited about the opportunity to contribute to your team.\n\n"
                 "I have experience building and moderating communities on Discord and Telegram, running ambassador "
                 "programs, and driving engagement across social platforms. I understand the importance of authentic "
                 "community building in the Web3 space.\n\n"
                 "I would love to discuss how my skills align with your needs.\n\n"
                 "Best regards\n\n"
                 "<i>Tip: Set ANTHROPIC_API_KEY to get AI-personalised cover letters.</i>")
            return

        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 800,
                "messages": [{
                    "role": "user",
                    "content": f"Write a professional, concise cover letter for this job. Keep it under 250 words. Job info: {content[:1500]}"
                }]
            },
            timeout=30
        )
        result = r.json().get("content", [{}])[0].get("text", "")
        if result:
            send(chat_id, f"📝 <b>Your Cover Letter</b>\n\n{result}")
        else:
            send(chat_id, "⚠️ Couldn't generate cover letter. Try again.")
    except Exception as e:
        send(chat_id, f"⚠️ Cover letter generation failed: {e}")


def handle_invite(chat_id):
    invite = f"https://t.me/{BOT_USERNAME}?start=ref_{chat_id}"
    user = db_get(chat_id)
    ref_count = user.get("referrals", 0) if user else 0
    send(chat_id,
         f"👥 <b>Invite Friends & Grow Together</b>\n\n"
         f"Share this link with anyone job hunting:\n"
         f"<code>{invite}</code>\n\n"
         f"📊 Your referrals: <b>{ref_count}</b>\n\n"
         f"📤 Ready-to-share message:\n\n"
         f"<i>Tired of manually searching job boards every day? "
         f"This free Telegram bot sends you daily remote job alerts — set your preferences once and forget it. "
         f"Works for every role: Community, Marketing, Tech, Sales, Finance, Executive, Web3 and more.\n\n"
         f"👉 {invite}</i>",
         [[{"text": "📤 Share Link", "url": f"https://t.me/share/url?url={invite}&text=Get%20free%20daily%20job%20alerts%20on%20Telegram%21"}]])


def handle_stop(chat_id):
    db_update(chat_id, {"active": False})
    send(chat_id, "⏸ <b>Alerts paused.</b>\n\nSend /start anytime to reactivate.",
         [[{"text": "▶️ Resume Alerts", "callback_data": "resume_alerts"}]])


def handle_resume(chat_id, cb_id=None):
    if cb_id: answer(cb_id, "✅ Alerts resumed!")
    db_update(chat_id, {"active": True})
    send(chat_id, "✅ <b>Alerts resumed!</b> You'll get your next batch tomorrow at 9am UTC.",
         kb_find_more())


def handle_help(chat_id):
    send(chat_id,
         "📖 <b>Remote Radar Commands</b>\n\n"
         "⚙️ <b>Setup</b>\n"
         "/start — Welcome & set up alerts\n"
         "/setup — Change your preferences\n"
         "/keywords — Add custom keywords\n"
         "/status — View current settings\n\n"
         "🔍 <b>Find Jobs</b>\n"
         "/find [role] — Instant search\n"
         "Example: <code>/find discord moderator</code>\n\n"
         "📊 <b>Market</b>\n"
         "/market — Most in-demand roles today\n\n"
         "✅ <b>Track Applications</b>\n"
         "/applied [title] at [company]\n"
         "/interview [title] at [company]\n"
         "/rejected [title] at [company]\n"
         "/offers — View your pipeline\n\n"
         "👁 <b>Watch Companies</b>\n"
         "/watch [company] — Get notified when they hire\n"
         "/unwatch [company] — Remove from watchlist\n\n"
         "📝 <b>AI Tools</b>\n"
         "/cover [URL or description] — Generate cover letter\n\n"
         "👥 <b>Invite</b>\n"
         "/invite — Share your referral link\n\n"
         "⏸ /stop — Pause alerts",
         kb_find_more())


# ── Main request handler ──────────────────────────────────────────────────────

def process_update(update):
    chat_id = None
    try:
        if "callback_query" in update:
            cb  = update["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            msg_id  = cb["message"]["message_id"]
            data    = cb.get("data", "")
            cb_id   = cb["id"]

            if data == "setup_start":    handle_setup_start(chat_id, msg_id, cb_id)
            elif data.startswith("cat_"): handle_category(chat_id, msg_id, data[4:], cb_id)
            elif data.startswith("sen_"): handle_seniority(chat_id, msg_id, data[4:], cb_id)
            elif data.startswith("loc_"): handle_location(chat_id, msg_id, data[4:], cb_id)
            elif data.startswith("ctype_"): handle_ctype(chat_id, msg_id, data[6:], cb_id)
            elif data == "find_now":     handle_find_now(chat_id, cb_id)
            elif data == "status":       answer(cb_id); handle_status(chat_id)
            elif data == "invite_link":  answer(cb_id); handle_invite(chat_id)
            elif data == "resume_alerts": handle_resume(chat_id, cb_id)
            return

        if "message" not in update:
            return

        msg  = update["message"]
        chat_id = msg["chat"]["id"]
        username = msg.get("from", {}).get("username", "")
        text = msg.get("text", "").strip()
        if not text:
            return

        # Check awaiting state
        user = db_get(chat_id)

        if user.get("awaiting_keywords") and not text.startswith("/"):
            db_update(chat_id, {"keywords": text, "awaiting_keywords": False})
            send(chat_id, f"✅ Keywords saved: <b>{text}</b>\n\nFinding matching jobs now...")
            send_jobs_now(chat_id, user | {"keywords": text})
            return

        if user.get("awaiting_cover") and not text.startswith("/"):
            db_update(chat_id, {"awaiting_cover": False})
            generate_cover_letter(chat_id, text)
            return

        # Commands
        if text.startswith("/start"):
            ref = text.replace("/start", "").strip()
            handle_start(chat_id, username, ref or None)
        elif text.startswith("/setup"):
            handle_start(chat_id, username)
        elif text.startswith("/keywords"):
            handle_keywords(chat_id, text)
        elif text.startswith("/find"):
            handle_find_command(chat_id, text)
        elif text.startswith("/market"):
            handle_market(chat_id)
        elif text.startswith("/applied"):
            handle_apply(chat_id, text)
        elif text.startswith("/interview"):
            handle_interview(chat_id, text)
        elif text.startswith("/rejected"):
            handle_rejected(chat_id, text)
        elif text.startswith("/offers"):
            handle_offers(chat_id)
        elif text.startswith("/watch"):
            handle_watch(chat_id, text)
        elif text.startswith("/unwatch"):
            handle_unwatch(chat_id, text)
        elif text.startswith("/cover"):
            handle_cover(chat_id, text)
        elif text.startswith("/invite"):
            handle_invite(chat_id)
        elif text.startswith("/status"):
            handle_status(chat_id)
        elif text.startswith("/stop"):
            handle_stop(chat_id)
        elif text.startswith("/help"):
            handle_help(chat_id)
        else:
            # Unknown message — show help
            handle_help(chat_id)

    except Exception as e:
        print(f"process_update error (chat {chat_id}): {e}")
        if chat_id:
            try:
                send(chat_id, "⚠️ Something went wrong. Please try again.")
            except Exception:
                pass


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
        try:
            process_update(json.loads(body))
        except Exception as e:
            print(f"Handler error: {e}")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    import sys, json as _json
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            process_update(_json.load(f))
