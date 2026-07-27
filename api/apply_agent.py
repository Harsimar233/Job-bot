"""
Review-first application drafting for Super Job Bot.

This module deliberately separates drafting from submission. It never claims
that an application was submitted and never invents candidate qualifications.
Site-specific submission adapters can be added later behind the same boundary.
"""
import json
import os
from urllib.parse import urlparse

import requests

from api import logger


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6")
OPENAI_TIMEOUT = max(20, min(int(os.environ.get("OPENAI_TIMEOUT", "90")), 180))
AUTO_APPLY_OWNER_USERNAME = (
    os.environ.get("AUTO_APPLY_OWNER_USERNAME", "Harsimarhs").strip().lstrip("@")
    or "Harsimarhs"
)
AUTO_APPLY_ALLOWED_CHAT_ID = os.environ.get(
    "AUTO_APPLY_ALLOWED_CHAT_ID", ""
).strip()

APPLICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "cover_letter": {"type": "string"},
        "why_fit": {"type": "string"},
        "questions_to_confirm": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["cover_letter", "why_fit", "questions_to_confirm"],
    "additionalProperties": False,
}


def _clean(value, limit=1200):
    return " ".join(str(value or "").split())[:limit]


def _response_text(payload):
    if payload.get("output_text"):
        return payload["output_text"]
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") in ("output_text", "text") and content.get("text"):
                return content["text"]
    return ""


def auto_apply_allowed(username="", chat_id=None):
    """
    Restrict the private beta to one Telegram account.

    A numeric chat ID is the strongest lock and wins when configured. Until the
    owner adds it, the exact Telegram username is used. Webhook secret
    verification prevents callers from forging Telegram update payloads.
    """
    if AUTO_APPLY_ALLOWED_CHAT_ID:
        return str(chat_id or "") == AUTO_APPLY_ALLOWED_CHAT_ID
    normalized = str(username or "").strip().lstrip("@").casefold()
    return normalized == AUTO_APPLY_OWNER_USERNAME.casefold()


def owner_username():
    return AUTO_APPLY_OWNER_USERNAME


def adapter_for(url):
    """Describe the form family without promising unsupported submission."""
    host = (urlparse(str(url or "")).netloc or "").lower()
    if "greenhouse.io" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "ashbyhq.com" in host:
        return "ashby"
    if "myworkdayjobs.com" in host or "workday.com" in host:
        return "workday"
    return "generic_web"


def profile_ready(profile):
    return bool(
        profile
        and profile.get("setup_step") == "ready"
        and profile.get("resume_file_id")
        and profile.get("full_name")
        and profile.get("email")
        and profile.get("phone")
    )


def _fallback_draft(job, profile):
    name = _clean(profile.get("full_name"), 100) or "Candidate"
    title = _clean(job.get("title"), 160) or "this role"
    company = _clean(job.get("company"), 120) or "your company"
    city = _clean(profile.get("current_city"), 100)
    location_sentence = f" I am currently based in {city}." if city else ""
    cover = (
        f"Dear Hiring Team, I am writing to apply for the {title} position at "
        f"{company}.{location_sentence} My resume is attached for your review. "
        "I would welcome the opportunity to discuss how my verified experience "
        "and skills align with this role. Thank you for your time and consideration."
        f"\n\nSincerely,\n{name}"
    )
    return {
        "cover_letter": cover,
        "why_fit": "Review the attached resume against the job requirements.",
        "questions_to_confirm": [
            "Confirm salary expectations if the form asks.",
            "Confirm notice period and earliest start date.",
            "Confirm work-authorization or visa-sponsorship answer for this country.",
        ],
        "generated_by": "safe_template",
    }


def build_application_draft(job, profile):
    """
    Generate a truthful draft using only candidate-provided profile fields.

    Email, phone, Telegram resume identifiers and other contact details are not
    sent to the model. The original resume remains stored by Telegram as a
    private file_id and is not uploaded to OpenAI in this version.
    """
    fallback = _fallback_draft(job, profile)
    if not OPENAI_API_KEY:
        return fallback

    candidate = {
        "full_name": _clean(profile.get("full_name"), 100),
        "current_city": _clean(profile.get("current_city"), 100),
    }
    posting = {
        "title": _clean(job.get("title"), 180),
        "company": _clean(job.get("company"), 140),
        "location": _clean(job.get("location"), 140),
        "description": _clean(job.get("description") or job.get("desc"), 1800),
        "visa_status": _clean(job.get("visa_status"), 30),
        "overseas_candidates": bool(job.get("overseas_candidates")),
    }
    prompt = f"""
Create a concise application draft using only the facts below.

Candidate facts:
{json.dumps(candidate, ensure_ascii=False)}

Job posting:
{json.dumps(posting, ensure_ascii=False)}

Rules:
- Never invent employment history, education, years of experience, skills,
  licenses, language ability, salary, work authorization, or availability.
- If evidence is missing, put the item in questions_to_confirm.
- Do not claim visa sponsorship unless the posting explicitly confirms it.
- Keep the cover letter under 180 words and make it suitable for copying into
  an application form.
""".strip()
    body = {
        "model": OPENAI_MODEL,
        "reasoning": {"effort": "low"},
        "input": prompt,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "application_draft",
                "strict": True,
                "schema": APPLICATION_SCHEMA,
            }
        },
    }
    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=OPENAI_TIMEOUT,
        )
        if response.status_code != 200:
            logger.error(
                f"Application draft failed ({response.status_code}): "
                f"{response.text[:240]}"
            )
            return fallback
        draft = json.loads(_response_text(response.json()))
        draft["generated_by"] = "openai"
        return draft
    except Exception as exc:
        logger.error(f"Application draft generation failed: {exc}")
        return fallback


def job_snapshot(job):
    """Keep only fields needed to review an application later."""
    return {
        "job_id": str(job.get("job_id") or job.get("_id") or ""),
        "title": _clean(job.get("title"), 180),
        "company": _clean(job.get("company"), 140),
        "location": _clean(job.get("location"), 140),
        "url": _clean(job.get("url"), 1000),
        "source": _clean(job.get("source"), 100),
        "description": _clean(job.get("description") or job.get("desc"), 1800),
        "visa_status": _clean(job.get("visa_status"), 30),
        "overseas_candidates": bool(job.get("overseas_candidates")),
    }
