"""
Super Job Bot — Structured Logger
Fix #1: Replaces silent except: pass with logged, trackable errors.
All failures are printed with context so Vercel logs become useful.
"""
import os
import traceback
from datetime import datetime

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")  # DEBUG | INFO | WARN | ERROR


def _ts():
    return datetime.utcnow().strftime("%H:%M:%S")


def debug(msg):
    if LOG_LEVEL == "DEBUG":
        print(f"[{_ts()}] DEBUG  {msg}")


def info(msg):
    print(f"[{_ts()}] INFO   {msg}")


def warn(msg):
    print(f"[{_ts()}] WARN   {msg}")


def error(msg, exc=None):
    print(f"[{_ts()}] ERROR  {msg}")
    if exc:
        # Print full traceback so Vercel logs capture it
        traceback.print_exc()


def scraper_result(source, count, exc=None):
    if exc:
        error(f"Scraper [{source}] FAILED: {exc}")
    else:
        info(f"Scraper [{source}] → {count} jobs")


def tg_send(chat_id, status_code, text_preview=""):
    if status_code == 200:
        debug(f"TG send OK → {chat_id}")
    elif status_code == 429:
        warn(f"TG rate limit → {chat_id}")
    else:
        error(f"TG send FAILED {status_code} → {chat_id} | {text_preview[:60]}")


def sb_error(method, path, status_code, body=""):
    error(f"Supabase {method.upper()} {path} → {status_code} | {body[:120]}")
