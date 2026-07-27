"""
Super Job Bot — Telegram Webhook
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
  #23 FIX: sb_patch now detects 0-row updates (silent RLS block) and
       falls back to sb_post upsert. Requires UNIQUE constraint on
       users.chat_id — run:
         ALTER TABLE users ADD CONSTRAINT users_chat_id_unique UNIQUE (chat_id);
       Also ensure SUPABASE_KEY is the service_role key, not anon.
"""
import os, json, time, requests, re, hmac
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler
from api import logger

BOT_TOKEN    = os.environ.get("JOB_BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
TG_API       = f"https://api.telegram.org/bot{BOT_TOKEN}"
BOT_USERNAME = os.environ.get("BOT_USERNAME", "RemoteJobsAlertBot")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
FIND_COOLDOWN = 60   # seconds between /find calls
MAX_WEBHOOK_BYTES = 1_000_000

WELCOME = """👋 <b>Welcome to Super Job Bot!</b>

Get fresh local, hybrid and remote job alerts on Telegram.

🌍 Job boards + company pages + AI web discovery
🎯 Waiter to director — every kind of role
⚡ Hot jobs flagged within 24h
📍 Search any city, region or country

Takes about 30 seconds to set up 👇

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
        if r.status_code not in (200, 201, 204):
            logger.sb_error("post", path, r.status_code, r.text)
            return False
        return True
    except Exception as e:
        logger.error(f"sb_post {path}: {e}")
        return False

def sb_patch(path, body):
    """
    PATCH with return=representation so we can detect silent 0-row updates.
    If 0 rows were updated (RLS blocking or row missing), logs a warning
    and returns False so callers can fall back to upsert.
    """
    try:
        r = requests.patch(
            f"{SUPABASE_URL}/rest/v1/{path}",
            headers=_hdr({"Prefer": "return=representation"}),
            json=body,
            timeout=10,
        )
        if r.status_code not in (200, 204):
            logger.sb_error("patch", path, r.status_code, r.text)
            return False
        # With return=representation, 200 returns updated rows as JSON array
        if r.status_code == 200:
            updated = r.json() if r.text.strip() else []
            if not updated:
                logger.warn(f"sb_patch {path}: 0 rows updated — "
                            f"RLS may be blocking UPDATE or row missing. "
                            f"Check: SUPABASE_KEY is service_role, not anon.")
                return False
        return True
    except Exception as e:
        logger.error(f"sb_patch {path}: {e}")
        return False

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
            "meta":    meta or {},
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
    """
    Try PATCH first. If it updates 0 rows (silent RLS failure), fall back
    to POST upsert. Upsert requires UNIQUE constraint on users.chat_id —
    run: ALTER TABLE users ADD CONSTRAINT users_chat_id_unique UNIQUE (chat_id);
    """
    ok = sb_patch(f"users?chat_id=eq.{chat_id}", data)
    if not ok:
        # Fallback: upsert. Requires UNIQUE constraint on chat_id.
        upsert_body = dict(data)
        upsert_body["chat_id"] = chat_id
        logger.warn(f"update_user {chat_id}: PATCH failed, falling back to upsert")
        sb_post("users", upsert_body, prefer="resolution=merge-duplicates")

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

def check_rate_limit(chat_id, user=None):
    """Pass user dict to avoid an extra DB round-trip."""
    if user is None:
        user = get_user(chat_id)
    last = user.get("last_find_at")
    if not last:
        return True, 0
    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        elapsed  = (datetime.now(timezone.utc) - last_dt).total_seconds()
        remaining = max(0, int(FIND_COOLDOWN - elapsed))
        return elapsed >= FIND_COOLDOWN, remaining
    except Exception:
        return True, 0

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

# ── Apply Agent helpers ───────────────────────────────────────────────────────

def get_candidate_profile(chat_id):
    rows = sb_get(f"candidate_profiles?chat_id=eq.{chat_id}&select=*&limit=1")
    return rows[0] if rows else {}

def is_autoapply_owner(chat_id, username=""):
    from api.apply_agent import auto_apply_allowed
    if not username:
        username = get_user(chat_id).get("username", "")
    return auto_apply_allowed(username=username, chat_id=chat_id)

def autoapply_access_message(chat_id):
    from api.apply_agent import owner_username
    owner = sanitize(owner_username(), 64)
    send(
        chat_id,
        "🔒 <b>Auto Apply is currently a private beta.</b>\n\n"
        f"Only <b>@{owner}</b> can use it right now. If you want access or "
        "want us to apply on your behalf, send a DM.",
        [[{"text": f"💬 DM @{owner}", "url": f"https://t.me/{owner}"}]],
    )

def set_candidate_profile(chat_id, data):
    payload = dict(data)
    payload["chat_id"] = chat_id
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    sb_post("candidate_profiles", payload, prefer="resolution=merge-duplicates")

def update_candidate_profile(chat_id, data):
    payload = dict(data)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    if not sb_patch(f"candidate_profiles?chat_id=eq.{chat_id}", payload):
        set_candidate_profile(chat_id, payload)

def _resume_profile_data(profile):
    data = profile.get("resume_profile") or {}
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (TypeError, ValueError):
            return {}
    return data if isinstance(data, dict) else {}

def _short_list(values, limit=6):
    return ", ".join(sanitize(value, 60) for value in (values or [])[:limit])

def send_resume_profile_preview(chat_id, profile):
    data = _resume_profile_data(profile)
    skills = _short_list(data.get("skills")) or "Not found"
    experience = data.get("work_experience") or []
    latest_role = "Not found"
    if experience and isinstance(experience[0], dict):
        role = sanitize(experience[0].get("title"), 80)
        company = sanitize(experience[0].get("employer"), 80)
        latest_role = " @ ".join(item for item in (role, company) if item) or "Not found"
    elif experience:
        latest_role = sanitize(experience[0], 160) or "Not found"
    send(
        chat_id,
        "✨ <b>I read your resume</b>\n\n"
        f"👤 Name: <b>{sanitize(profile.get('full_name')) or 'Not found'}</b>\n"
        f"✉️ Email: {sanitize(profile.get('email')) or 'Not found'}\n"
        f"📞 Phone: {sanitize(profile.get('phone')) or 'Not found'}\n"
        f"📍 Current city: {sanitize(profile.get('current_city')) or 'Not found'}\n"
        f"💼 Latest role: {latest_role}\n"
        f"🛠 Skills: {skills}\n\n"
        "Please confirm these details before the Apply Agent uses them.",
        [
            [{"text": "✅ Looks Right", "callback_data": "autoapply_profile_confirm"}],
            [{"text": "✏️ Enter Details Manually", "callback_data": "autoapply_profile_edit"}],
        ],
    )

def _next_missing_profile_step(profile):
    name = str(profile.get("full_name") or "").strip()
    if len(name) < 2:
        return "awaiting_name"
    email = str(profile.get("email") or "").strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return "awaiting_email"
    phone_digits = re.sub(r"\D", "", str(profile.get("phone") or ""))
    if len(phone_digits) < 8 or len(phone_digits) > 15:
        return "awaiting_phone"
    if len(str(profile.get("current_city") or "").strip()) < 2:
        return "awaiting_city"
    return ""

def confirm_resume_profile(chat_id):
    profile = get_candidate_profile(chat_id)
    missing_step = _next_missing_profile_step(profile)
    if missing_step:
        prompts = {
            "awaiting_name": "I couldn't find your full legal name. Please type it:",
            "awaiting_email": "I couldn't find your email. Please type it:",
            "awaiting_phone": "I couldn't find your phone number. Include country code:",
            "awaiting_city": "I couldn't confirm your current city and country. Please type it:",
        }
        update_candidate_profile(chat_id, {"setup_step": missing_step})
        send(chat_id, prompts[missing_step])
        return
    update_candidate_profile(chat_id, {
        "setup_step": "ready",
        "auto_apply_mode": "review",
    })
    track(chat_id, "autoapply_setup_complete", {"resume_extracted": True})
    send(
        chat_id,
        "✅ <b>Apply Agent is ready</b>\n\n"
        "Your resume details are saved and Review Mode is ON. New matching "
        "jobs will be added to /applications. Nothing is finally submitted "
        "without you.",
        [[{"text": "🔍 Find Jobs Now", "callback_data": "find_jobs"},
          {"text": "📥 Review Queue", "callback_data": "applications"}]],
    )

def queue_applications(chat_id, jobs, username=""):
    """Queue matches only for users who explicitly enabled review mode."""
    if not is_autoapply_owner(chat_id, username):
        return 0
    profile = get_candidate_profile(chat_id)
    if profile.get("auto_apply_mode") != "review":
        return 0
    from api.apply_agent import adapter_for, job_snapshot
    rows = []
    for job in jobs:
        job_id = str(job.get("job_id") or job.get("_id") or "")
        if not job_id:
            continue
        rows.append({
            "chat_id": chat_id,
            "job_id": job_id,
            "status": "queued",
            "adapter": adapter_for(job.get("url")),
            "apply_method": "review_then_open",
            "job_snapshot": job_snapshot(job),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
    if not rows:
        return 0
    if not sb_post(
        "applications?on_conflict=chat_id,job_id",
        rows,
        prefer="resolution=ignore-duplicates,return=minimal",
    ):
        logger.error(f"Could not queue applications for chat {chat_id}")
        return 0

    # Never claim that jobs were queued until Supabase confirms the rows exist.
    queued_rows = sb_get(
        f"applications?chat_id=eq.{chat_id}&select=job_id&limit=200"
    )
    queued_ids = {str(row.get("job_id") or "") for row in queued_rows}
    requested_ids = {row["job_id"] for row in rows}
    return len(requested_ids & queued_ids)

def handle_autoapply(chat_id, username=""):
    if not is_autoapply_owner(chat_id, username):
        autoapply_access_message(chat_id)
        return
    profile = get_candidate_profile(chat_id)
    if profile.get("setup_step") == "ready":
        enabled = profile.get("auto_apply_mode") == "review"
        status = "🟢 Review mode ON" if enabled else "⚪ Off"
        send(
            chat_id,
            "🤖 <b>Apply Agent</b>\n\n"
            f"Status: <b>{status}</b>\n"
            f"Resume: {sanitize(profile.get('resume_file_name') or 'Not uploaded')}\n"
            f"Candidate: {sanitize(profile.get('full_name'))}\n\n"
            "When ON, matching jobs are auto-queued and the agent prepares a "
            "truthful application draft. You approve before opening/submitting "
            "any employer form.",
            [
                [{"text": "✅ Turn Review Mode On", "callback_data": "autoapply_on"},
                 {"text": "⏹ Turn Off", "callback_data": "autoapply_off"}],
                [{"text": "📥 Review Queue", "callback_data": "applications"},
                 {"text": "📄 Replace Resume", "callback_data": "autoapply_resume"}],
            ],
        )
        return
    pending_prompts = {
        "awaiting_resume": "📄 Upload your resume as PDF, DOC or DOCX (max 10 MB).",
        "processing_resume": "⏳ Your resume is being read. Please wait a moment.",
        "awaiting_name": "What is your full legal name?",
        "awaiting_email": "What email should job applications use?",
        "awaiting_phone": "What phone number should applications use? Include country code.",
        "awaiting_city": "What city and country do you currently live in?",
    }
    if profile.get("setup_step") == "awaiting_confirmation":
        send_resume_profile_preview(chat_id, profile)
        return
    if profile.get("setup_step") in pending_prompts:
        send(
            chat_id,
            "🤖 <b>Continue Apply Agent setup</b>\n\n"
            + pending_prompts[profile["setup_step"]],
        )
        return
    send(
        chat_id,
        "🤖 <b>Set up Apply Agent</b>\n\n"
        "• Upload your resume once\n"
        "• Add name, email, phone and current city\n"
        "• Matching jobs are queued automatically\n"
        "• AI drafts never invent qualifications\n"
        "• <b>You approve before any final application step</b>\n\n"
        "With your consent, your resume is sent to OpenAI once to extract your "
        "profile. The bot stores the extracted details and a private Telegram "
        "file reference.",
        [[{"text": "🔐 I Agree — Set It Up", "callback_data": "autoapply_consent"}],
         [{"text": "❌ Not Now", "callback_data": "status"}]],
    )

def handle_resume_document(chat_id, document, username=""):
    if not is_autoapply_owner(chat_id, username):
        autoapply_access_message(chat_id)
        return
    profile = get_candidate_profile(chat_id)
    if profile.get("setup_step") == "processing_resume":
        send(chat_id, "⏳ Your resume is already being read. Please wait a moment.")
        return
    if profile.get("setup_step") != "awaiting_resume":
        send(chat_id, "Use /autoapply first, then upload your resume.")
        return
    name = str(document.get("file_name") or "resume")
    mime = str(document.get("mime_type") or "").lower()
    size = int(document.get("file_size") or 0)
    allowed = (
        mime in (
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        or name.lower().endswith((".pdf", ".doc", ".docx"))
    )
    if not allowed:
        send(chat_id, "Please upload a PDF, DOC or DOCX resume.")
        return
    if size > 10 * 1024 * 1024:
        send(chat_id, "Resume is too large. Please keep it under 10 MB.")
        return
    update_candidate_profile(chat_id, {"setup_step": "processing_resume"})
    send(chat_id, "🧠 Reading your resume and filling your profile...")
    from api.resume_parser import extract_resume_profile
    extracted = extract_resume_profile(document)
    if extracted:
        update_candidate_profile(chat_id, {
            "resume_file_id": document.get("file_id"),
            "resume_file_unique_id": document.get("file_unique_id"),
            "resume_file_name": name[:180],
            "resume_mime_type": mime[:120],
            "resume_size": size,
            "resume_profile": extracted,
            "resume_processed_at": datetime.now(timezone.utc).isoformat(),
            "full_name": str(extracted.get("full_name") or "")[:120],
            "email": str(extracted.get("email") or "")[:180],
            "phone": str(extracted.get("phone") or "")[:40],
            "current_city": str(extracted.get("current_city") or "")[:120],
            "setup_step": "awaiting_confirmation",
        })
        send_resume_profile_preview(chat_id, get_candidate_profile(chat_id))
        return

    # Keep setup usable when OpenAI is unavailable or cannot read a document.
    already_complete = all(
        profile.get(field)
        for field in ("full_name", "email", "phone", "current_city")
    )
    update_candidate_profile(chat_id, {
        "resume_file_id": document.get("file_id"),
        "resume_file_unique_id": document.get("file_unique_id"),
        "resume_file_name": name[:180],
        "resume_mime_type": mime[:120],
        "resume_size": size,
        "setup_step": "ready" if already_complete else "awaiting_name",
    })
    if already_complete:
        send(
            chat_id,
            "✅ Resume replaced. Automatic reading was unavailable, so your "
            "existing confirmed profile was kept.",
            [[{"text": "📥 Review Queue", "callback_data": "applications"}]],
        )
        return
    send(
        chat_id,
        "✅ Resume saved, but automatic reading was unavailable. "
        "We'll finish the four essential fields manually.\n\n"
        "What is your <b>full legal name</b>?",
    )

def handle_apply_profile_text(chat_id, text, profile, username=""):
    step = profile.get("setup_step")
    value = text.strip()
    if step and step not in ("not_started", "ready") and not is_autoapply_owner(
        chat_id, username
    ):
        autoapply_access_message(chat_id)
        return True
    if step == "awaiting_resume":
        send(chat_id, "Please upload your resume as a PDF, DOC or DOCX file.")
        return True
    if step == "processing_resume":
        send(chat_id, "Your resume is still being read. Please wait a moment.")
        return True
    if step == "awaiting_confirmation":
        send_resume_profile_preview(chat_id, profile)
        return True
    if step == "awaiting_name":
        if len(value) < 2 or len(value) > 120:
            send(chat_id, "Please enter your full name (2–120 characters).")
            return True
        update_candidate_profile(chat_id, {
            "full_name": value,
            "setup_step": "awaiting_email",
        })
        send(chat_id, "What email should job applications use?")
        return True
    if step == "awaiting_email":
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            send(chat_id, "That email does not look valid. Please try again.")
            return True
        update_candidate_profile(chat_id, {
            "email": value[:180],
            "setup_step": "awaiting_phone",
        })
        send(chat_id, "What phone number should applications use? Include country code.")
        return True
    if step == "awaiting_phone":
        digits = re.sub(r"\D", "", value)
        if len(digits) < 8 or len(digits) > 15:
            send(chat_id, "Please enter a valid phone number with country code.")
            return True
        update_candidate_profile(chat_id, {
            "phone": value[:40],
            "setup_step": "awaiting_city",
        })
        send(chat_id, "What city and country do you currently live in?")
        return True
    if step == "awaiting_city":
        if len(value) < 2 or len(value) > 120:
            send(chat_id, "Please enter a city and country.")
            return True
        update_candidate_profile(chat_id, {
            "current_city": value,
            "setup_step": "ready",
            "auto_apply_mode": "review",
        })
        track(chat_id, "autoapply_setup_complete")
        send(
            chat_id,
            "✅ <b>Apply Agent is ready</b>\n\n"
            "New matching jobs will be added to your review queue. Use "
            "/applications anytime. Nothing is finally submitted without you.",
            [[{"text": "🔍 Find Jobs Now", "callback_data": "find_jobs"},
              {"text": "📥 Review Queue", "callback_data": "applications"}]],
        )
        return True
    return False

def _application_job(application):
    snapshot = application.get("job_snapshot") or {}
    if snapshot:
        return snapshot
    rows = sb_get(
        f"jobs?job_id=eq.{application.get('job_id','')}&select=*&limit=1"
    )
    return rows[0] if rows else {}

def prepare_application(chat_id, job_id, username=""):
    if not is_autoapply_owner(chat_id, username):
        autoapply_access_message(chat_id)
        return
    from api.apply_agent import (
        adapter_for, build_application_draft, job_snapshot, profile_ready,
    )
    profile = get_candidate_profile(chat_id)
    if not profile_ready(profile):
        send(chat_id, "Set up your resume and profile first with /autoapply.")
        handle_autoapply(chat_id, username)
        return
    rows = sb_get(f"jobs?job_id=eq.{job_id}&select=*&limit=1")
    if not rows:
        queued = sb_get(
            f"applications?chat_id=eq.{chat_id}&job_id=eq.{job_id}&select=*&limit=1"
        )
        job = _application_job(queued[0]) if queued else {}
    else:
        job = rows[0]
    if not job:
        send(chat_id, "This job is no longer available in the cache.")
        return
    send(chat_id, "🤖 Preparing a truthful application draft...")
    draft = build_application_draft(job, profile)
    now = datetime.now(timezone.utc).isoformat()
    application_payload = {
        "chat_id": chat_id,
        "job_id": job_id,
        "status": "awaiting_approval",
        "adapter": adapter_for(job.get("url")),
        "apply_method": "review_then_open",
        "cover_letter": draft.get("cover_letter", ""),
        "why_fit": draft.get("why_fit", ""),
        "questions_to_confirm": draft.get("questions_to_confirm", []),
        "job_snapshot": job_snapshot(job),
        "updated_at": now,
    }
    application_path = (
        f"applications?chat_id=eq.{chat_id}&job_id=eq.{job_id}"
    )
    existing_application = sb_get(f"{application_path}&select=id&limit=1")
    if existing_application:
        saved = sb_patch(application_path, {
            key: value for key, value in application_payload.items()
            if key not in ("chat_id", "job_id")
        })
    else:
        saved = sb_post(
            "applications?on_conflict=chat_id,job_id",
            application_payload,
            prefer="resolution=merge-duplicates,return=minimal",
        )
    applications = sb_get(
        f"applications?chat_id=eq.{chat_id}&job_id=eq.{job_id}&select=*&limit=1"
    )
    if (
        not saved
        or not applications
        or applications[0].get("status") != "awaiting_approval"
    ):
        cover = sanitize(draft.get("cover_letter"), 1000)
        url = sanitize_url(job.get("url"))
        buttons = [[{"text": "🌐 Open Employer Form", "url": url}]] if url else None
        send(
            chat_id,
            "⚠️ <b>Draft prepared, but Supabase could not save it.</b>\n\n"
            f"<b>Copy this cover letter:</b>\n<i>{cover}</i>\n\n"
            "You can still continue manually below. To permanently repair the "
            "review queue, run the latest auto-apply SQL upgrade in Supabase.",
            buttons,
        )
        return
    application = applications[0]
    questions = application.get("questions_to_confirm") or []
    question_text = "\n".join(f"• {sanitize(q, 180)}" for q in questions[:3])
    cover = sanitize(application.get("cover_letter"), 1000)
    job = _application_job(application)
    send(
        chat_id,
        "🤖 <b>Application ready for review</b>\n\n"
        f"💼 <b>{sanitize(job.get('title'))}</b>\n"
        f"🏢 {sanitize(job.get('company'))}\n\n"
        f"<b>Draft cover letter</b>\n<i>{cover}</i>\n\n"
        + (f"<b>Please confirm on the employer form</b>\n{question_text}\n\n"
           if question_text else "")
        + "Approval records your consent and gives you the original employer "
          "form. It does not falsely mark the application as submitted.",
        [[{"text": "✅ Approve & Continue", "callback_data": f"applyapprove_{application['id']}"}],
         [{"text": "⏭ Skip This Job", "callback_data": f"applyskip_{application['id']}"}]],
    )
    track(chat_id, "application_drafted", {"job_id": job_id})

def handle_applications(chat_id, username=""):
    if not is_autoapply_owner(chat_id, username):
        autoapply_access_message(chat_id)
        return
    queue_path = (
        f"applications?chat_id=eq.{chat_id}"
        "&status=in.(queued,awaiting_approval,manual_required)"
        "&select=*&order=created_at.desc&limit=8"
    )
    rows = sb_get(queue_path)

    # Self-heal old/failed queues. This also covers jobs found immediately
    # before Review Mode was enabled.
    if not rows:
        profile = get_candidate_profile(chat_id)
        if profile.get("auto_apply_mode") == "review":
            user = get_user(chat_id)
            _, disliked_ids = get_user_feedback(chat_id)
            recovery_jobs = [
                job for job in get_cached_jobs()
                if job.get("job_id", "") not in disliked_ids
                and job_matches_user(job, user)
            ][:8]
            if recovery_jobs:
                queue_applications(chat_id, recovery_jobs, username)
                rows = sb_get(queue_path)

    if not rows:
        send(
            chat_id,
            "📥 <b>Your application queue is empty.</b>\n\n"
            "Review Mode is ON, but no matching cached jobs could be queued yet. "
            "Use /find once, then open /applications again.\n\n"
            "If jobs appear in /find but this remains empty, the Supabase "
            "<code>applications</code> table needs the auto-apply SQL upgrade.",
        )
        return
    send(chat_id, f"📥 <b>{len(rows)} applications to review</b>")
    for application in rows:
        job = _application_job(application)
        status = application.get("status", "queued").replace("_", " ").title()
        text = (
            f"💼 <b>{sanitize(job.get('title') or 'Job')}</b>\n"
            f"🏢 {sanitize(job.get('company'))}\n"
            f"📍 {sanitize(job.get('location'))}\n"
            f"🤖 {status}"
        )
        if application.get("status") == "manual_required":
            url = sanitize_url(job.get("url"))
            buttons = []
            if url:
                buttons.append([{"text": "🌐 Open Employer Form", "url": url}])
            buttons.append([{
                "text": "✅ Mark as Submitted",
                "callback_data": f"applysubmitted_{application['id']}",
            }])
        elif application.get("status") == "awaiting_approval":
            buttons = [
                [{"text": "✅ Approve & Continue",
                  "callback_data": f"applyapprove_{application['id']}"}],
                [{"text": "⏭ Skip", "callback_data": f"applyskip_{application['id']}"}],
            ]
        else:
            buttons = [[{"text": "🤖 Prepare Draft",
                         "callback_data": f"applyprep_{application['job_id']}"}]]
        send(chat_id, text, buttons)

def approve_application(chat_id, application_id, username=""):
    if not is_autoapply_owner(chat_id, username):
        autoapply_access_message(chat_id)
        return
    rows = sb_get(
        f"applications?id=eq.{application_id}&chat_id=eq.{chat_id}&select=*&limit=1"
    )
    if not rows:
        send(chat_id, "Application not found.")
        return
    application = rows[0]
    job = _application_job(application)
    url = sanitize_url(job.get("url"))
    update = {
        "status": "manual_required",
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    sb_patch(f"applications?id=eq.{application_id}&chat_id=eq.{chat_id}", update)
    send(
        chat_id,
        "✅ <b>Approved</b>\n\n"
        "Open the original employer form below. Upload your saved resume, copy "
        "the draft if needed, and complete employer-specific questions or "
        "CAPTCHA yourself.\n\n"
        f"<b>Cover letter</b>\n<i>{sanitize(application.get('cover_letter'), 1800)}</i>",
        (
            [[{"text": "🌐 Open Employer Form", "url": url}],
             [{"text": "✅ Mark as Submitted",
               "callback_data": f"applysubmitted_{application_id}"}]]
            if url
            else [[{"text": "✅ Mark as Submitted",
                    "callback_data": f"applysubmitted_{application_id}"}]]
        ),
    )
    track(chat_id, "application_approved", {"job_id": application.get("job_id")})

def skip_application(chat_id, application_id, username=""):
    if not is_autoapply_owner(chat_id, username):
        autoapply_access_message(chat_id)
        return
    sb_patch(
        f"applications?id=eq.{application_id}&chat_id=eq.{chat_id}",
        {
            "status": "skipped",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    track(chat_id, "application_skipped", {"application_id": application_id})

def mark_application_submitted(chat_id, application_id, username=""):
    if not is_autoapply_owner(chat_id, username):
        autoapply_access_message(chat_id)
        return
    rows = sb_get(
        f"applications?id=eq.{application_id}&chat_id=eq.{chat_id}&select=job_id&limit=1"
    )
    if not rows:
        send(chat_id, "Application not found.")
        return
    now = datetime.now(timezone.utc).isoformat()
    sb_patch(
        f"applications?id=eq.{application_id}&chat_id=eq.{chat_id}",
        {"status": "submitted", "submitted_at": now, "updated_at": now},
    )
    track(chat_id, "application_submitted", {"job_id": rows[0].get("job_id")})
    send(chat_id, "🎉 Marked as submitted. Good luck!")

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

def format_job_card(job, show_actions=True, allow_autoapply=False):
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
    if job.get("visa_status") == "confirmed" or job.get("visa"):
        lines.append("🛂 <b>Employer visa/work-permit support confirmed</b>")
    elif job.get("overseas_candidates"):
        lines.append("🌍 Overseas applicants accepted")
    mode = (job.get("work_mode") or "").lower()
    employment = (job.get("employment_type") or "").replace("_", " ").title()
    if mode and mode != "unknown":
        lines.append(f"🧭 {sanitize(mode.title())}")
    if employment and employment.lower() != "unknown":
        lines.append(f"🕒 {sanitize(employment)}")
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
        if allow_autoapply:
            buttons.insert(
                0,
                [{"text": "🤖 Prepare Application",
                  "callback_data": f"applyprep_{job_id}"}],
            )
    return text, buttons

# ── Keyboards ─────────────────────────────────────────────────────────────────

def kb_main():
    return [[{"text": "🔍 Find Jobs", "callback_data": "find_jobs"}],
            [{"text": "🌍 Abroad Job + Work Visa", "callback_data": "abroad_setup"}],
            [{"text": "📊 Today's Progress", "callback_data": "ai_progress"},
             {"text": "📥 Applications", "callback_data": "applications"}],
            [{"text": "🤖 Auto Apply — Private Beta", "callback_data": "autoapply"}],
            [{"text": "⚙️ Set Up / Preferences", "callback_data": "setup_start"},
             {"text": "⏹ Pause",        "callback_data": "stop"}]]

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
        [{"text": "📍 Any other city / region", "callback_data": "loc_custom"}],
        [{"text": "🌐 Worldwide",        "callback_data": "loc_worldwide"}],
    ]

def kb_after_jobs(chat_id, username=""):
    apply_row = (
        [{"text": "🤖 Application Queue", "callback_data": "applications"}]
        if is_autoapply_owner(chat_id, username)
        else [{"text": "🤖 Request Auto Apply", "callback_data": "autoapply"}]
    )
    return [
        [{"text": "🔍 Find More", "callback_data": "find_jobs"}],
        apply_row,
        [{"text": "🌍 Abroad + Visa Mode", "callback_data": "abroad_setup"}],
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
    "custom":    "📍 Custom location",
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
        from api.jobs import matches_user
        return matches_user(job, user)
    except Exception as e:
        logger.error(f"job_matches_user: {e}")
        return False

def send_jobs_from_cache(chat_id, user, page=0, keyword_override=None):
    # Pagination is part of an existing search and must not hit the /find cooldown.
    if page == 0:
        allowed, remaining = check_rate_limit(chat_id, user)
        if not allowed:
            send(chat_id, f"⏳ Please wait {remaining}s before searching again.")
            return

        send(chat_id, "🔍 Searching...")
        update_user(chat_id, {
            "last_find_at":   datetime.now(timezone.utc).isoformat(),
            "last_active_at": datetime.now(timezone.utc).isoformat(),
        })
    track(chat_id, "find_jobs", {"page": page})

    cached = get_cached_jobs()
    if not cached:
        send(chat_id, "No jobs cached yet — the daily scan runs at 9am UTC.", kb_main())
        return

    from api.jobs import feedback_affinity, score
    keywords = keyword_override or user.get("keywords", "")

    liked_ids, disliked_ids = get_user_feedback(chat_id)
    liked_jobs = [j for j in cached if j.get("job_id", "") in liked_ids]

    # Bulk fetch all sent job IDs in ONE query instead of one per job
    sent_rows = sb_get(f"sent_jobs?chat_id=eq.{chat_id}&select=job_id")
    sent_ids  = {r["job_id"] for r in sent_rows} if sent_rows else set()

    if keyword_override:
        search_user = dict(user)
        search_user["keywords"] = keyword_override
        search_user["category"] = "all"
        matched = [
            j for j in cached
            if keyword_override.lower() in (j.get("title","") or "").lower()
            and j.get("job_id","") not in disliked_ids
            and (not user.get("relocation_only") or job_matches_user(j, search_user))
        ]
        showing_previous = False
    else:
        matched = [j for j in cached
                   if job_matches_user(j, user)
                   and j.get("job_id","") not in sent_ids
                   and j.get("job_id","") not in disliked_ids]
        showing_previous = False

        # "No new matches" used to look like the bot had found zero jobs on the
        # internet. If every matching cached job was already shown, repeat the
        # best recent matches instead of presenting a misleading empty result.
        if not matched:
            matched = [
                j for j in cached
                if job_matches_user(j, user)
                and j.get("job_id","") not in disliked_ids
            ]
            showing_previous = bool(matched)

    matched.sort(key=lambda j: (
        -(50 if j.get("job_id","") in liked_ids else 0),
        -feedback_affinity(j, liked_jobs),
        -score(j.get("title",""), keywords),
        not j.get("hot", False)
    ))

    per_page = 5
    # Profile searches mark each delivered job as sent. On the next page those
    # jobs are already excluded, so the next batch starts at zero.
    start    = page * per_page if (keyword_override or showing_previous) else 0
    batch    = matched[start:start + per_page]
    has_more = not keyword_override and len(matched) > start + per_page

    if not batch:
        if user.get("relocation_only"):
            tips = (
                "📭 <b>No verified visa-supported matches in the cache yet.</b>\n\n"
                "The bot intentionally hides jobs that require existing local work rights. "
                "The next scheduled scan will search your target countries again.\n\n"
                "Try broader role keywords such as "
                "<code>waiter, kitchen helper, housekeeping, warehouse, store assistant</code>."
            )
        else:
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
    if showing_previous:
        header = (
            "🔄 <b>No brand-new matches since your last check.</b>\n"
            f"Here are {len(batch)} best recent matches again"
        )
    else:
        header = f"🔍 <b>{len(batch)} jobs for you</b>"
    if hot_count:
        header += f" · ⚡ {hot_count} posted today"
    header += f"\n📡 {', '.join(sources[:4])}"
    send(chat_id, header)

    allow_autoapply = is_autoapply_owner(chat_id, user.get("username", ""))
    for job in batch:
        text, buttons = format_job_card(
            job, show_actions=True, allow_autoapply=allow_autoapply
        )
        send(chat_id, text, buttons)
        if not keyword_override:
            mark_sent(chat_id, job["job_id"])
        time.sleep(0.1)

    queued_count = (
        queue_applications(chat_id, batch, user.get("username", ""))
        if not keyword_override else 0
    )
    footer_kb = kb_after_jobs(chat_id, user.get("username", ""))
    if has_more:
        footer_kb = [[{"text": f"➡️ Load {min(5, len(matched) - start - per_page)} more",
                       "callback_data": f"find_page_{page+1}"}]] + footer_kb

    queue_note = (
        f"\n🤖 {queued_count} added to your application review queue."
        if queued_count else ""
    )
    send(
        chat_id,
        f"✅ Tap 👍 on good matches — it trains your feed.{queue_note}",
        footer_kb,
    )

# ── Onboarding FSM ────────────────────────────────────────────────────────────

SETUP_STEPS = [
    "awaiting_role", "awaiting_seniority", "awaiting_location",
    "awaiting_custom_location", "awaiting_ctype",
]

def get_current_step(user):
    for step in SETUP_STEPS:
        if user.get(step):
            return step
    return None

def _reset_to_step1(chat_id):
    """
    Set awaiting_role=True via update_user which tries PATCH first,
    then falls back to upsert if PATCH updates 0 rows (RLS or missing row).
    """
    update_user(chat_id, {
        "awaiting_role":      True,
        "awaiting_seniority": False,
        "awaiting_location":  False,
        "awaiting_custom_location": False,
        "awaiting_ctype":     False,
        "awaiting_keywords":  False,
        "awaiting_abroad_countries": False,
    })
    # Verify the write actually landed
    verify = get_user(chat_id)
    if not verify.get("awaiting_role"):
        logger.error(f"_reset_to_step1 {chat_id}: awaiting_role STILL False after write — "
                     f"check SUPABASE_KEY (needs service_role) and UNIQUE constraint on chat_id")

# ── Handlers ──────────────────────────────────────────────────────────────────

def handle_start(chat_id, username, ref_code=None):
    existing = get_user(chat_id)
    is_new   = not existing

    if existing:
        update_user(chat_id, {"username": username or ""})
        step = get_current_step(existing)
        if step == "awaiting_role":
            send(chat_id,
                 "⚙️ <b>Step 1 of 3 — Your Role</b>\n\n"
                 "What job role are you looking for?\n\n"
                 "<b>Examples:</b>\n"
                 "• <code>Community Manager</code>\n"
                 "• <code>Web3 Marketing Manager</code>\n"
                 "• <code>Discord Moderator</code>\n"
                 "• <code>Software Engineer</code>\n\n"
                 "Type your role and send 👇",
                 [[{"text": "❌ Cancel", "callback_data": "status"}]])
            return
        elif step in (
            "awaiting_seniority", "awaiting_location",
            "awaiting_custom_location", "awaiting_ctype",
        ):
            _reset_to_step1(chat_id)
            send(chat_id,
                 "👋 Let's pick up where you left off.\n\n"
                 "<b>Step 1 of 3 — Your Role</b>\n\nType your role and send 👇",
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
            "relocation_only":     False,
            "target_countries":    "",
            "awaiting_keywords":  False,
            "awaiting_abroad_countries": False,
            "awaiting_role":      False,
            "awaiting_seniority": False,
            "awaiting_location":  False,
            "awaiting_custom_location": False,
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


def handle_abroad(chat_id, text=""):
    user = get_user(chat_id)
    if not user:
        set_user(chat_id, {
            "active": False,
            "setup_complete": False,
            "relocation_only": True,
            "target_countries": "",
        })
        user = get_user(chat_id)
    countries = sanitize(
        re.sub(
            r"[^A-Za-zÀ-ÿ ,.&()/-]",
            "",
            text.replace("/abroad", "", 1).strip().lstrip(","),
        ),
        max_len=200,
    )
    if not user or not user.get("setup_complete"):
        update_user(chat_id, {
            "relocation_only": True,
            "target_countries": countries,
            "awaiting_abroad_countries": False,
        })
        send(
            chat_id,
            "🌍 <b>Abroad + Work Visa mode selected.</b>\n\n"
            "First tell me the role you can do. You can enter multiple roles, "
            "for example:\n<code>dishwasher, waiter, store assistant, warehouse</code>",
        )
        step1_role(chat_id, 0)
        return
    if not countries:
        update_user(chat_id, {"awaiting_abroad_countries": True})
        send(
            chat_id,
            "🌍 <b>Which countries should I target?</b>\n\n"
            "Type comma-separated countries, for example:\n"
            "<code>UAE, Japan, Singapore, New Zealand</code>\n\n"
            "Or type <code>Worldwide</code>.",
            [[{"text": "❌ Turn off abroad mode", "callback_data": "abroad_off"}]],
        )
        return
    update_user(chat_id, {
        "relocation_only": True,
        "target_countries": countries,
        "remote_only": False,
        "awaiting_abroad_countries": False,
        "last_find_at": None,
        "active": True,
    })
    track(chat_id, "abroad_mode_enabled", {"countries": countries})
    send(
        chat_id,
        f"✅ <b>Abroad + Work Visa mode is ON</b>\n\n"
        f"🎯 Countries: {countries}\n"
        "🛂 Only jobs with credible employer visa/work-permit support or "
        "explicit overseas-candidate acceptance will match.\n\n"
        "Fresh visa-first discovery runs with the scheduled scan.",
        [[{"text": "🔍 Check Matching Jobs", "callback_data": "find_jobs"},
          {"text": "📋 View Profile", "callback_data": "status"}]],
    )


def handle_abroad_off(chat_id):
    update_user(chat_id, {
        "relocation_only": False,
        "target_countries": "",
        "awaiting_abroad_countries": False,
        "last_find_at": None,
    })
    track(chat_id, "abroad_mode_disabled")
    send(chat_id, "✅ Abroad mode is off. Regular local/remote matching restored.", kb_main())


def handle_status(chat_id):
    user = get_user(chat_id)
    if not user or not user.get("setup_complete"):
        send(chat_id, "You haven't set up alerts yet.", kb_main())
        return
    kws       = user.get("keywords", "") or "—"
    status    = "✅ Active" if user.get("active") else "⏸ Paused"
    location_label = (
        sanitize(user.get("location", "Worldwide"))
        if user.get("location_key") == "custom"
        else LOC_LABELS.get(user.get("location_key", "worldwide"), "Worldwide")
    )
    abroad_line = (
        f"\n🌍 Abroad + Visa: ✅ {sanitize(user.get('target_countries') or 'Worldwide')}"
        if user.get("relocation_only")
        else "\n🌍 Abroad + Visa: Off"
    )
    apply_button = (
        {"text": "🤖 Application Queue", "callback_data": "applications"}
        if is_autoapply_owner(chat_id, user.get("username", ""))
        else {"text": "🤖 Request Auto Apply", "callback_data": "autoapply"}
    )
    send(
        chat_id,
        f"📋 <b>Your Job Profile</b>\n\n"
        f"🎯 {sanitize(kws)}\n"
        f"🎓 {SEN_LABELS.get(user.get('seniority', 'all'), 'All Levels')}\n"
        f"📍 {location_label}\n"
        f"🏢 {CTYPE_LABELS.get(user.get('company_type', 'any'), 'Any')}\n"
        f"📡 Alerts: {status}{abroad_line}",
        [[{"text": "🔍 Find Jobs", "callback_data": "find_jobs"},
          {"text": "🔖 Saved", "callback_data": "show_saved"}],
         [{"text": "✏️ Edit Preferences", "callback_data": "setup_start"},
          {"text": "🌍 Visa Settings", "callback_data": "abroad_setup"}],
         [apply_button],
         [{"text": "⏹ Pause Alerts", "callback_data": "stop"}]],
    )

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
         f"<i>Send this to anyone job hunting — fresh local and remote alerts, set up in 60 seconds.</i>")

def handle_stop(chat_id):
    update_user(chat_id, {"active": False})
    track(chat_id, "paused")
    send(chat_id, "⏸ Alerts paused.",
         [[{"text": "▶️ Resume Alerts", "callback_data": "resume_alerts"}]])

def handle_resume_alerts(chat_id):
    user = get_user(chat_id)
    if not user.get("setup_complete"):
        step1_role(chat_id)
        return
    update_user(chat_id, {
        "active": True,
        "last_active_at": datetime.now(timezone.utc).isoformat(),
    })
    track(chat_id, "resumed")
    send(
        chat_id,
        "▶️ Alerts resumed. Fresh matches will arrive on the next scan.",
        [[{"text": "🔍 Find Jobs Now", "callback_data": "find_jobs"}]],
    )

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
             "✏️ <b>Update keywords</b>\n\nType your new keywords:\n\n"
             "<code>community manager, discord</code>\n"
             "<code>python engineer, backend</code>")
        return
    update_user(chat_id, {
        "keywords":          keywords,
        "awaiting_keywords": False,
        "last_find_at":      None,
    })
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

def step1_role(chat_id, msg_id=None):
    _reset_to_step1(chat_id)
    if msg_id is not None:
        edit(chat_id, msg_id, "⚙️ Setting up your alerts...")
    send(chat_id,
         "⚙️ <b>Step 1 of 3 — Your Role</b>\n\n"
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
         f"⚙️ <b>Step 2 of 3 — Level</b>\n\nWhat seniority are you targeting?",
         kb_seniority())

def step3_location(chat_id, msg_id, seniority, cb_id):
    answer(cb_id, f"✅ {SEN_LABELS.get(seniority, seniority)}")
    update_user(chat_id, {"seniority": seniority, "awaiting_seniority": False,
                           "awaiting_location": True})
    edit(chat_id, msg_id,
         f"✅ Level: {SEN_LABELS.get(seniority, seniority)}\n\n"
         f"⚙️ <b>Step 3 of 3 — Location</b>\n\nWhere are you looking to work?",
         kb_location())

def step4_company_type(chat_id, msg_id, loc_key, cb_id):
    if loc_key == "custom":
        answer(cb_id, "✅ Type your location")
        update_user(chat_id, {
            "awaiting_location": False,
            "awaiting_custom_location": True,
        })
        edit(
            chat_id,
            msg_id,
            "📍 <b>Type any city, region or country</b>\n\n"
            "Examples: <code>Amritsar</code>, <code>Dubai</code>, "
            "<code>Ontario, Canada</code>",
        )
        return
    loc_name, remote_only = LOC_MAP.get(loc_key, ("Worldwide", False))
    answer(cb_id, f"✅ {LOC_LABELS.get(loc_key, loc_key)}")
    update_user(chat_id, {"location": loc_name, "location_key": loc_key,
                           "remote_only": remote_only, "awaiting_location": False,
                           "awaiting_ctype": False})
    finish_setup(chat_id, msg_id, "any", None)

def finish_setup(chat_id, msg_id, ctype, cb_id):
    if cb_id:
        answer(cb_id, f"✅ {CTYPE_LABELS.get(ctype, ctype)}")
    update_user(chat_id, {"company_type": ctype, "active": True, "setup_complete": True,
                           "awaiting_ctype": False, "last_find_at": None})
    user = get_user(chat_id)
    location_label = (
        sanitize(user.get("location", "Worldwide"))
        if user.get("location_key") == "custom"
        else LOC_LABELS.get(user.get("location_key", "worldwide"), "Worldwide")
    )
    track(chat_id, "setup_complete")
    send(chat_id,
         f"🎉 <b>You're all set!</b>\n\n"
         f"🎯 {sanitize(user.get('keywords', ''))}\n"
         f"🎓 {SEN_LABELS.get(user.get('seniority', 'all'), 'All Levels')}\n"
         f"📍 {location_label}\n"
         "\n"
         "Alerts go out 3× daily. Find jobs right now 👇",
         [[{"text": "🔍 Find Jobs Now", "callback_data": "find_jobs"}]])
    if user.get("relocation_only") and not user.get("target_countries"):
        handle_abroad(chat_id)

# ── Conversational AI assistant ───────────────────────────────────────────────

def _looks_like_natural_job_search(text):
    q = re.sub(r"\s+", " ", str(text or "").strip().casefold())
    search_words = (
        "find", "search", "dhund", "dhoond", "dikha", "show me", "jobs chahiye",
        "job chahiye", "best jobs", "matching jobs",
    )
    tracking_words = (
        "apply", "applied", "application", "pending", "queue", "draft",
        "submitted", "progress", "status", "saved",
    )
    return (
        ("job" in q or "vacanc" in q or "naukri" in q)
        and any(word in q for word in search_words)
        and not any(word in q for word in tracking_words)
    )


def handle_conversation(chat_id, text, username=""):
    """Answer normal messages without forcing users to remember commands."""
    user = get_user(chat_id)
    if not user or not user.get("setup_complete"):
        send(
            chat_id,
            "Pehle apna job profile set up kar lete hain—sirf role, level aur "
            "location chahiye.",
        )
        step1_role(chat_id)
        return

    if _looks_like_natural_job_search(text):
        q = str(text or "").casefold()
        abroad_words = (
            "visa", "abroad", "overseas", "dubai", "uae", "new zealand",
            "canada", "europe", "germany", "australia", "relocation",
        )
        if any(word in q for word in abroad_words):
            send(
                chat_id,
                "🌍 Abroad search samajh gaya. Target countries confirm kar do:",
            )
            handle_abroad(chat_id)
        else:
            send_jobs_from_cache(chat_id, user)
        return

    applications = sb_get(
        f"applications?chat_id=eq.{chat_id}"
        "&select=status,created_at,updated_at,approved_at,submitted_at,job_snapshot"
        "&order=created_at.desc&limit=50"
    )
    saved_jobs = sb_get(
        f"saved_jobs?chat_id=eq.{chat_id}"
        "&select=job_title,company,source,created_at"
        "&order=created_at.desc&limit=20"
    )
    sent_jobs = sb_get(
        f"sent_jobs?chat_id=eq.{chat_id}"
        "&select=job_id,sent_at&order=sent_at.desc&limit=100"
    )
    profile = get_candidate_profile(chat_id)

    from api.job_assistant import answer_job_question
    answer_text = answer_job_question(
        text,
        user=user,
        profile=profile,
        applications=applications,
        saved_jobs=saved_jobs,
        sent_jobs=sent_jobs,
    )
    track(chat_id, "assistant_question", {"length": len(str(text or ""))})
    send(
        chat_id,
        sanitize(answer_text, 3900),
        [[{"text": "🔍 Find Jobs", "callback_data": "find_jobs"},
          {"text": "📥 Applications", "callback_data": "applications"}]],
    )

# ── Main update processor ─────────────────────────────────────────────────────

def process_update(update):
    try:
        if "message" in update:
            msg      = update["message"]
            chat_id  = msg["chat"]["id"]
            username = msg.get("from", {}).get("username", "")
            text     = msg.get("text", "") or ""

            if msg.get("document"):
                if not get_user(chat_id):
                    set_user(chat_id, {
                        "username": username,
                        "active": False,
                        "setup_complete": False,
                    })
                handle_resume_document(chat_id, msg["document"], username)
                return

            if text and not text.startswith("/"):
                user = get_user(chat_id)
                profile = get_candidate_profile(chat_id)
                if handle_apply_profile_text(chat_id, text, profile, username):
                    return
                logger.info(f"Text from {chat_id}: '{text[:40]}' | "
                            f"awaiting_role={user.get('awaiting_role')} "
                            f"awaiting_keywords={user.get('awaiting_keywords')} "
                            f"awaiting_search={user.get('awaiting_search')} "
                            f"awaiting_abroad={user.get('awaiting_abroad_countries')}")

                if user.get("awaiting_abroad_countries"):
                    handle_abroad(chat_id, text)
                    return

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
                        "last_find_at":      None,
                    })
                    send(chat_id, f"✅ Keywords updated: <b>{kw}</b>")
                    send_jobs_from_cache(chat_id, get_user(chat_id))
                    return

                if user.get("awaiting_custom_location"):
                    location = sanitize(text.strip(), max_len=120)
                    if len(location) < 2:
                        send(chat_id, "Please type a city, region or country.")
                        return
                    update_user(chat_id, {
                        "location": location,
                        "location_key": "custom",
                        "remote_only": False,
                        "awaiting_custom_location": False,
                        "awaiting_ctype": False,
                    })
                    finish_setup(chat_id, None, "any", None)
                    return

                if user.get("awaiting_search"):
                    query = sanitize(text.strip(), max_len=150)
                    update_user(chat_id, {"awaiting_search": False})
                    send_jobs_from_cache(chat_id, user, keyword_override=query)
                    return

                handle_conversation(chat_id, text, username)
                return

            if text.startswith("/"):
                text = text.split("@")[0]

            if text.startswith("/start"):
                parts    = text.split(" ", 1)
                ref_code = parts[1].strip() if len(parts) > 1 else None
                handle_start(chat_id, username, ref_code)
            elif text.startswith("/keywords"):
                handle_keywords(chat_id, text)
            elif text.startswith("/search"):
                handle_search(chat_id, text)
            elif text.startswith("/abroad"):
                handle_abroad(chat_id, text)
            elif text.startswith("/local"):
                handle_abroad_off(chat_id)
            elif text.startswith("/autoapply"):
                if not get_user(chat_id):
                    set_user(chat_id, {
                        "username": username,
                        "active": False,
                        "setup_complete": False,
                    })
                handle_autoapply(chat_id, username)
            elif text.startswith("/applications"):
                handle_applications(chat_id, username)
            elif text.startswith("/find"):
                user = get_user(chat_id)
                if user.get("setup_complete"):
                    send_jobs_from_cache(chat_id, user)
                else:
                    step1_role(chat_id)
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
                    _reset_to_step1(chat_id)
                    send(chat_id,
                         "⚙️ <b>Step 1 of 3 — Your Role</b>\n\nType your role and send 👇",
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
                     "📖 <b>Quick Help</b>\n\n"
                     "🔍 /find — Find personalized jobs\n"
                     "🌍 /abroad UAE, New Zealand — Visa-first mode\n"
                     "🤖 /autoapply — Auto Apply private beta\n"
                     "🔖 /saved — Saved jobs\n"
                     "⚙️ /status — Profile and settings\n\n"
                     "💬 <b>Or just type normally</b>\n"
                     "<code>Aaj maine kaunsi jobs apply ki?</code>\n"
                     "<code>Pending applications batao</code>\n"
                     "<code>Mere liye best jobs dikhao</code>\n\n"
                     "<b>More tools</b>\n"
                     "/search waiter · /keywords · /watch Company\n"
                     "/local · /stop · /delete",
                     kb_main())

        elif "callback_query" in update:
            cb       = update["callback_query"]
            chat_id  = cb["from"]["id"]
            username = cb["from"].get("username", "")
            msg_id   = cb["message"]["message_id"]
            data     = cb.get("data", "")
            cb_id    = cb["id"]

            current_user = get_user(chat_id)
            if not current_user:
                set_user(chat_id, {"username": username, "active": False,
                                   "setup_complete": False})
            elif username and current_user.get("username") != username:
                update_user(chat_id, {"username": username})

            private_apply_action = (
                data.startswith((
                    "applyprep_", "applyapprove_", "applyskip_", "applysubmitted_",
                ))
                or data in {
                    "autoapply_consent", "autoapply_resume", "autoapply_on",
                    "autoapply_off", "autoapply_profile_confirm",
                    "autoapply_profile_edit", "applications",
                }
            )
            if private_apply_action and not is_autoapply_owner(chat_id, username):
                answer(cb_id, "Private beta — DM @Harsimarhs")
                autoapply_access_message(chat_id)
                return

            if data.startswith("applyprep_"):
                job_id = data.replace("applyprep_", "")
                answer(cb_id, "Preparing application...")
                prepare_application(chat_id, job_id, username)

            elif data.startswith("applyapprove_"):
                application_id = data.replace("applyapprove_", "")
                answer(cb_id, "Approved")
                approve_application(chat_id, application_id, username)

            elif data.startswith("applyskip_"):
                application_id = data.replace("applyskip_", "")
                skip_application(chat_id, application_id, username)
                answer(cb_id, "Skipped")

            elif data.startswith("applysubmitted_"):
                application_id = data.replace("applysubmitted_", "")
                answer(cb_id, "Marked as submitted")
                mark_application_submitted(chat_id, application_id, username)

            elif data.startswith("like_"):
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
                     "Share Super Job Bot with someone who's still searching 👇",
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
                         f"Get fresh local and remote job alerts: {invite}")

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
                user = get_user(chat_id)
                if user.get("setup_complete"):
                    answer(cb_id, "Searching...")
                    send_jobs_from_cache(chat_id, user)
                else:
                    answer(cb_id, "Let's set up your profile")
                    step1_role(chat_id, msg_id)
            elif data == "ai_progress":
                answer(cb_id, "Checking today's progress...")
                handle_conversation(chat_id, "aaj ka status", username)
            elif data == "abroad_setup":
                answer(cb_id)
                handle_abroad(chat_id)
            elif data == "abroad_off":
                answer(cb_id)
                handle_abroad_off(chat_id)
            elif data == "show_saved":
                answer(cb_id)
                handle_saved(chat_id)
            elif data == "autoapply":
                answer(cb_id)
                handle_autoapply(chat_id, username)
            elif data == "autoapply_consent":
                answer(cb_id)
                set_candidate_profile(chat_id, {
                    "setup_step": "awaiting_resume",
                    "auto_apply_mode": "off",
                    "consent_version": "resume-ai-extraction-v2",
                    "consented_at": datetime.now(timezone.utc).isoformat(),
                })
                send(
                    chat_id,
                    "📄 Upload your resume now as PDF, DOC or DOCX (max 10 MB).\n\n"
                    "It will be sent to OpenAI once to extract your profile, "
                    "then you can confirm or edit the result.",
                )
            elif data == "autoapply_resume":
                answer(cb_id)
                update_candidate_profile(chat_id, {"setup_step": "awaiting_resume"})
                send(chat_id, "📄 Upload the replacement PDF, DOC or DOCX resume.")
            elif data == "autoapply_profile_confirm":
                answer(cb_id, "Details confirmed")
                confirm_resume_profile(chat_id)
            elif data == "autoapply_profile_edit":
                answer(cb_id, "Let's edit your details")
                update_candidate_profile(chat_id, {"setup_step": "awaiting_name"})
                send(chat_id, "What is your <b>full legal name</b>?")
            elif data == "autoapply_on":
                answer(cb_id, "Review mode enabled")
                profile = get_candidate_profile(chat_id)
                if profile.get("setup_step") == "ready":
                    update_candidate_profile(chat_id, {"auto_apply_mode": "review"})
                    send(chat_id, "🟢 Apply Agent review mode is ON.")
                else:
                    handle_autoapply(chat_id, username)
            elif data == "autoapply_off":
                answer(cb_id, "Apply Agent paused")
                update_candidate_profile(chat_id, {"auto_apply_mode": "off"})
                send(chat_id, "⏹ Apply Agent is off. Existing queue is kept.")
            elif data == "applications":
                answer(cb_id)
                handle_applications(chat_id, username)
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
            elif data == "resume_alerts":
                answer(cb_id, "Alerts resumed")
                handle_resume_alerts(chat_id)
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
        if not TELEGRAM_WEBHOOK_SECRET:
            logger.error("TELEGRAM_WEBHOOK_SECRET is required")
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b"Webhook secret is not configured")
            return
        provided = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(provided, TELEGRAM_WEBHOOK_SECRET):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"Forbidden")
            return
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > MAX_WEBHOOK_BYTES:
            self.send_response(413)
            self.end_headers()
            self.wfile.write(b"Invalid payload size")
            return
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
        self.wfile.write(b"Super Job Bot is running.")

    def log_message(self, *args):
        pass
