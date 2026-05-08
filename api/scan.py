"""
Job Bot — Fast version using only RSS feeds and public APIs.
No HTML scraping (too slow for Vercel's timeout).
"""
import os, json, hashlib, logging, time
import requests, feedparser
from http.server import BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("job-bot")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID   = os.environ.get("CHAT_ID", "")

KEYWORDS = os.environ.get("KEYWORDS",
    "community,ambassador,growth,discord,telegram,dao,defi,nft,kol,"
    "galxe,zealy,moderator,ecosystem,web3,crypto,blockchain,protocol,"
    "marketing,partnerships,acquisition,retention"
)
EXCLUDE = os.environ.get("EXCLUDE",
    "engineer,developer,solidity,backend,frontend,devops,"
    "10+ years,china only,japanese required,korean required"
)

KEYWORDS_LIST = [k.strip().lower() for k in KEYWORDS.split(",") if k.strip()]
EXCLUDE_LIST  = [k.strip().lower() for k in EXCLUDE.split(",") if k.strip()]
SEEN_FILE     = "/tmp/seen_jobs.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JobBot/1.0)",
    "Accept": "application/rss+xml, application/xml, text/xml, application/json",
}

def load_seen():
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_seen(seen):
    try:
        with open(SEEN_FILE, "w") as f:
            json.dump(list(seen), f)
    except Exception:
        pass

def jid(url):
    return hashlib.md5(url.encode()).hexdigest()

def job(title, company, location, url, source, desc="", tags=None, salary=""):
    return {
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "location": (location or "Remote").strip(),
        "url": (url or "").strip(),
        "source": source,
        "description": desc or "",
        "tags": tags or [],
        "salary": (salary or "").strip(),
        "_id": jid(url or ""),
    }

def fetch_rss(urls):
    for url in (urls if isinstance(urls, list) else [urls]):
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            if r.status_code == 200 and len(r.text) > 200:
                return feedparser.parse(r.text)
        except Exception:
            continue
    return None

def split_co(title):
    for sep in [" at ", " — ", " - "]:
        if sep in title:
            p = title.split(sep, 1)
            return p[0].strip(), p[1].strip()
    return title.strip(), ""

def src_cryptojobslist():
    jobs = []
    feed = fetch_rss(["https://cryptojobslist.com/rss.xml", "https://cryptojobslist.com/rss"])
    if not feed:
        return []
    for e in feed.entries:
        t, c = split_co(e.get("title", ""))
        tags = [x.term for x in e.get("tags", [])]
        jobs.append(job(t, c, "Remote", e.get("link",""), "CryptoJobsList", e.get("summary",""), tags))
    logger.info(f"CryptoJobsList: {len(jobs)}")
    return jobs

def src_web3career():
    jobs = []
    feed = fetch_rss(["https://web3.career/rss.xml", "https://web3.career/feed.xml"])
    if not feed:
        return []
    for e in feed.entries:
        t, c = split_co(e.get("title", ""))
        tags = [x.term for x in e.get("tags", [])]
        jobs.append(job(t, c, "Remote", e.get("link",""), "Web3.career", e.get("summary",""), tags))
    logger.info(f"Web3.career: {len(jobs)}")
    return jobs

def src_weworkremotely():
    jobs = []
    feed = fetch_rss("https://weworkremotely.com/categories/remote-sales-and-marketing-jobs.rss")
    if not feed:
        return []
    for e in feed.entries:
        t = e.get("title", "")
        c = ""
        if ": " in t:
            c, t = t.split(": ", 1)
        jobs.append(job(t.strip(), c.strip(), "Remote", e.get("link",""), "WeWorkRemotely", e.get("summary","")))
    logger.info(f"WeWorkRemotely: {len(jobs)}")
    return jobs

def src_remoteok():
    jobs = []
    try:
        r = requests.get("https://remoteok.com/api?tags=crypto,web3,community",
                         headers={**HEADERS, "Accept": "application/json"}, timeout=8)
        if r.status_code != 200:
            return []
        data = r.json()
        for j in data[1:]:
            if not isinstance(j, dict) or not j.get("url"):
                continue
            tags = j.get("tags", [])
            jobs.append(job(
                j.get("position",""), j.get("company",""), "Remote",
                j.get("url",""), "RemoteOK",
                j.get("description",""),
                tags if isinstance(tags, list) else [],
                str(j.get("salary",""))
            ))
        logger.info(f"RemoteOK: {len(jobs)}")
    except Exception as e:
        logger.error(f"RemoteOK: {e}")
    return jobs

def src_jobicy():
    jobs = []
    seen = set()
    for q in ["community+manager+web3", "ambassador+crypto", "growth+web3"]:
        try:
            r = requests.get(
                f"https://jobicy.com/api/v2/remote-jobs?count=50&jobCategory=marketing&keyWord={q}",
                headers=HEADERS, timeout=8)
            if r.status_code != 200:
                continue
            for j in r.json().get("jobs", []):
                u = j.get("url","")
                if not u or u in seen:
                    continue
                seen.add(u)
                jobs.append(job(
                    j.get("jobTitle",""), j.get("companyName",""),
                    j.get("jobGeo","Remote"), u, "Jobicy",
                    j.get("jobDescription",""), [j.get("jobCategory","")]
                ))
        except Exception as e:
            logger.error(f"Jobicy {q}: {e}")
    logger.info(f"Jobicy: {len(jobs)}")
    return jobs

def score(j):
    text = f"{j['title']} {j['description']} {' '.join(j['tags'])}".lower()
    hits = sum(1 for k in KEYWORDS_LIST if k in text)
    return round((hits / max(len(KEYWORDS_LIST), 1)) * 100, 1)

def excluded(j):
    text = f"{j['title']} {j['description']}".lower()
    return any(k in text for k in EXCLUDE_LIST)

def tg(text):
    if not BOT_TOKEN or not CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text,
                  "parse_mode": "Markdown", "disable_web_page_preview": True},
            timeout=10)
    except Exception as e:
        logger.error(f"TG: {e}")

def fmt(j, rank):
    s = j["_score"]
    bar = "🟩" * min(int(s/10), 10) or "⬜"
    lines = [f"*#{rank} {j['title']}*", f"🏢 {j['company'] or 'Unknown'}", f"📍 {j['location']}"]
    if j["salary"]:
        lines.append(f"💰 {j['salary']}")
    if j["tags"]:
        lines.append("🏷 " + " ".join(f"`{t}`" for t in j["tags"][:5]))
    lines += [f"📊 Match: {bar} {s:.0f}%", f"🔗 [Apply Now]({j['url']})", f"_via {j['source']}_"]
    return "\n".join(lines)

def run_scan():
    if not BOT_TOKEN or not CHAT_ID:
        logger.error("Missing credentials")
        return

    all_jobs = []
    for fn in [src_cryptojobslist, src_web3career, src_weworkremotely, src_remoteok, src_jobicy]:
        try:
            all_jobs += fn()
        except Exception as e:
            logger.error(f"{fn.__name__}: {e}")

    logger.info(f"Total: {len(all_jobs)}")

    seen = load_seen()
    unique = {}
    for j in all_jobs:
        if j["_id"] not in seen and j["_id"] not in unique and j["url"]:
            unique[j["_id"]] = j

    scored = []
    for j in unique.values():
        if excluded(j):
            continue
        s = score(j)
        if s >= 15:
            j["_score"] = s
            scored.append(j)

    scored.sort(key=lambda j: j["_score"], reverse=True)
    top = scored[:10]

    for j in top:
        seen.add(j["_id"])
    save_seen(seen)

    if not top:
        tg("No new matching jobs found in this scan.")
        return

    sources = list({j["source"] for j in top})
    tg(f"🔍 *{len(top)} new job matches*\nSources: {', '.join(sources)}\nSorted by match score ↓")
    for i, j in enumerate(top, 1):
        tg(fmt(j, i))
        time.sleep(0.3)

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        run_scan()
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Done.")
    def log_message(self, format, *args):
        pass
