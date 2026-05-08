"""
Job Bot — Vercel Serverless Function
Scrapes 9 web3 job sources. Sends community/growth role matches to Telegram.
"""
import os, json, hashlib, logging, time
import requests, feedparser
from http.server import BaseHTTPRequestHandler
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("job-bot")

# ─── Config ──────────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID   = os.environ.get("CHAT_ID", "")

KEYWORDS = os.environ.get("KEYWORDS",
    "community,ambassador,growth,discord,telegram,dao,defi,nft,kol,"
    "galxe,zealy,moderator,ecosystem,web3,crypto,blockchain,protocol,"
    "marketing,social media,partnerships,acquisition,retention"
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
    "Accept": "text/html,application/xhtml+xml,application/xml,application/rss+xml",
}


# ─── Dedup ───────────────────────────────────────────────────────────────────

def load_seen():
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_seen(seen: set):
    try:
        with open(SEEN_FILE, "w") as f:
            json.dump(list(seen), f)
    except Exception:
        pass

def job_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_job(title, company, location, url, source, desc="", tags=None, salary=""):
    return {
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "location": (location or "Remote").strip(),
        "url": (url or "").strip(),
        "source": source,
        "description": desc or "",
        "tags": tags or [],
        "salary": (salary or "").strip(),
        "_score": 0.0,
        "_id": job_id(url or ""),
    }

def fetch_rss(urls):
    for url in (urls if isinstance(urls, list) else [urls]):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200 and len(r.text) > 200:
                return feedparser.parse(r.text)
        except Exception:
            continue
    return None

def split_company(title):
    for sep in [" at ", " — ", " - "]:
        if sep in title:
            parts = title.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return title.strip(), ""


# ─── Source 1: CryptoJobsList ────────────────────────────────────────────────

def scrape_cryptojobslist():
    jobs = []
    feed = fetch_rss(["https://cryptojobslist.com/rss.xml", "https://cryptojobslist.com/rss"])
    if not feed:
        return []
    for e in feed.entries:
        title, company = split_company(e.get("title", ""))
        tags = [t.term for t in e.get("tags", [])]
        jobs.append(make_job(title, company, "Remote", e.get("link",""), "CryptoJobsList", e.get("summary",""), tags))
    logger.info(f"CryptoJobsList: {len(jobs)}")
    return jobs


# ─── Source 2: Web3.career ───────────────────────────────────────────────────

def scrape_web3career():
    jobs = []
    feed = fetch_rss(["https://web3.career/rss.xml", "https://web3.career/feed.xml"])
    if not feed:
        return []
    for e in feed.entries:
        title, company = split_company(e.get("title", ""))
        tags = [t.term for t in e.get("tags", [])]
        jobs.append(make_job(title, company, "Remote", e.get("link",""), "Web3.career", e.get("summary",""), tags))
    logger.info(f"Web3.career: {len(jobs)}")
    return jobs


# ─── Source 3: Jobicy public API ─────────────────────────────────────────────

def scrape_jobicy():
    jobs = []
    seen_urls = set()
    queries = [
        "community+manager", "ambassador+web3", "growth+crypto", "discord+moderator"
    ]
    for q in queries:
        try:
            r = requests.get(
                f"https://jobicy.com/api/v2/remote-jobs?count=50&jobCategory=marketing&keyWord={q}",
                headers=HEADERS, timeout=15
            )
            if r.status_code != 200:
                continue
            for j in r.json().get("jobs", []):
                url = j.get("url", "")
                if url in seen_urls or not url:
                    continue
                seen_urls.add(url)
                jobs.append(make_job(
                    j.get("jobTitle",""), j.get("companyName",""),
                    j.get("jobGeo","Remote"), url, "Jobicy",
                    j.get("jobDescription",""), [j.get("jobCategory","")]
                ))
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Jobicy {q}: {e}")
    logger.info(f"Jobicy: {len(jobs)}")
    return jobs


# ─── Source 4: We Work Remotely ──────────────────────────────────────────────

def scrape_weworkremotely():
    jobs = []
    feed = fetch_rss([
        "https://weworkremotely.com/categories/remote-sales-and-marketing-jobs.rss",
        "https://weworkremotely.com/categories/all-other-remote-jobs.rss",
    ])
    if not feed:
        return []
    for e in feed.entries:
        title = e.get("title", "")
        company = ""
        if ": " in title:
            company, title = title.split(": ", 1)
        jobs.append(make_job(title.strip(), company.strip(), "Remote", e.get("link",""), "WeWorkRemotely", e.get("summary","")))
    logger.info(f"WeWorkRemotely: {len(jobs)}")
    return jobs


# ─── Source 5: RemoteOK ───────────────────────────────────────────────────────

def scrape_remoteok():
    jobs = []
    try:
        r = requests.get(
            "https://remoteok.com/api?tags=crypto,web3,community",
            headers={**HEADERS, "Accept": "application/json"}, timeout=15
        )
        if r.status_code != 200:
            return []
        data = r.json()
        for j in data[1:]:
            if not isinstance(j, dict) or not j.get("url"):
                continue
            tags = j.get("tags", [])
            jobs.append(make_job(
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


# ─── Source 6: CryptocurrencyJobs.co ─────────────────────────────────────────

def scrape_cryptocurrencyjobs():
    jobs = []
    try:
        r = requests.get("https://cryptocurrencyjobs.co/marketing/", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select("a.job")[:30]:
            title_el   = card.select_one(".job-title")
            company_el = card.select_one(".job-organization-name")
            loc_el     = card.select_one(".job-location")
            href = card.get("href", "")
            if not title_el or not href:
                continue
            jobs.append(make_job(
                title_el.get_text(strip=True),
                company_el.get_text(strip=True) if company_el else "",
                loc_el.get_text(strip=True) if loc_el else "Remote",
                f"https://cryptocurrencyjobs.co{href}" if href.startswith("/") else href,
                "CryptocurrencyJobs",
            ))
        logger.info(f"CryptocurrencyJobs: {len(jobs)}")
    except Exception as e:
        logger.error(f"CryptocurrencyJobs: {e}")
    return jobs


# ─── Source 7: Remote3.co ─────────────────────────────────────────────────────

def scrape_remote3():
    jobs = []
    try:
        r = requests.get("https://remote3.co/remote-jobs?category=community-manager", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select("div[class*='job'], article[class*='job'], li[class*='job']")[:30]:
            title_el = card.select_one("h2, h3, [class*='title']")
            company_el = card.select_one("[class*='company']")
            link_el = card.select_one("a[href]")
            if not title_el or not link_el:
                continue
            href = link_el.get("href", "")
            jobs.append(make_job(
                title_el.get_text(strip=True),
                company_el.get_text(strip=True) if company_el else "",
                "Remote",
                f"https://remote3.co{href}" if href.startswith("/") else href,
                "Remote3",
            ))
        logger.info(f"Remote3: {len(jobs)}")
    except Exception as e:
        logger.error(f"Remote3: {e}")
    return jobs


# ─── Source 8: Wellfound ──────────────────────────────────────────────────────

def scrape_wellfound():
    jobs = []
    try:
        r = requests.get(
            "https://wellfound.com/jobs?remote=true&keywords=community+manager+web3",
            headers=HEADERS, timeout=15
        )
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select("div[data-test='StartupResult']")[:20]:
            title_el   = card.select_one("a[data-test='job-title']")
            company_el = card.select_one("a[data-test='startup-link']")
            salary_el  = card.select_one("[data-test='comp']")
            tags_els   = card.select("[data-test='tag']")
            if not title_el:
                continue
            href = title_el.get("href", "")
            jobs.append(make_job(
                title_el.get_text(strip=True),
                company_el.get_text(strip=True) if company_el else "",
                "Remote",
                f"https://wellfound.com{href}" if href.startswith("/") else href,
                "Wellfound",
                tags=[t.get_text(strip=True) for t in tags_els],
                salary=salary_el.get_text(strip=True) if salary_el else "",
            ))
        logger.info(f"Wellfound: {len(jobs)}")
    except Exception as e:
        logger.error(f"Wellfound: {e}")
    return jobs


# ─── Source 9: LinkedIn ───────────────────────────────────────────────────────

def scrape_linkedin():
    jobs = []
    try:
        r = requests.get(
            "https://www.linkedin.com/jobs/search/?keywords=web3+community+manager+ambassador&f_WT=2&f_TPR=r86400",
            headers=HEADERS, timeout=15
        )
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select("div.base-card")[:20]:
            title_el   = card.select_one("h3.base-search-card__title")
            company_el = card.select_one("h4.base-search-card__subtitle")
            loc_el     = card.select_one("span.job-search-card__location")
            link_el    = card.select_one("a.base-card__full-link")
            if not title_el or not link_el:
                continue
            jobs.append(make_job(
                title_el.get_text(strip=True),
                company_el.get_text(strip=True) if company_el else "",
                loc_el.get_text(strip=True) if loc_el else "Remote",
                link_el.get("href","").split("?")[0],
                "LinkedIn",
            ))
        logger.info(f"LinkedIn: {len(jobs)}")
        time.sleep(1)
    except Exception as e:
        logger.error(f"LinkedIn: {e}")
    return jobs


# ─── Scoring ─────────────────────────────────────────────────────────────────

def score(job: dict) -> float:
    text = f"{job['title']} {job['description']} {' '.join(job['tags'])}".lower()
    hits = sum(1 for k in KEYWORDS_LIST if k in text)
    return round((hits / max(len(KEYWORDS_LIST), 1)) * 100, 1)

def is_excluded(job: dict) -> bool:
    text = f"{job['title']} {job['description']}".lower()
    return any(k in text for k in EXCLUDE_LIST)


# ─── Telegram ────────────────────────────────────────────────────────────────

def tg(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text,
                  "parse_mode": "Markdown", "disable_web_page_preview": True},
            timeout=10,
        )
    except Exception as e:
        logger.error(f"Telegram: {e}")

def format_job(job: dict, rank: int) -> str:
    s = job["_score"]
    bar = "🟩" * min(int(s / 10), 10) or "⬜"
    lines = [
        f"*#{rank} {job['title']}*",
        f"🏢 {job['company'] or 'Unknown'}",
        f"📍 {job['location']}",
    ]
    if job["salary"]:
        lines.append(f"💰 {job['salary']}")
    if job["tags"]:
        lines.append("🏷 " + " ".join(f"`{t}`" for t in job["tags"][:5]))
    lines += [
        f"📊 Match: {bar} {s:.0f}%",
        f"🔗 [Apply Now]({job['url']})",
        f"_via {job['source']}_",
    ]
    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────

def run_scan():
    if not BOT_TOKEN or not CHAT_ID:
        logger.error("Missing BOT_TOKEN or CHAT_ID")
        return

    scrapers = [
        scrape_cryptojobslist,
        scrape_web3career,
        scrape_jobicy,
        scrape_weworkremotely,
        scrape_remoteok,
        scrape_cryptocurrencyjobs,
        scrape_remote3,
        scrape_wellfound,
        scrape_linkedin,
    ]

    all_jobs = []
    for fn in scrapers:
        try:
            all_jobs += fn()
        except Exception as e:
            logger.error(f"{fn.__name__} crashed: {e}")

    logger.info(f"Total raw: {len(all_jobs)}")

    seen_ids = load_seen()
    unique = {}
    for job in all_jobs:
        jid = job["_id"]
        if jid not in seen_ids and jid not in unique and job["url"]:
            unique[jid] = job

    scored = []
    for job in unique.values():
        if is_excluded(job):
            continue
        s = score(job)
        if s >= 15:
            job["_score"] = s
            scored.append(job)

    scored.sort(key=lambda j: j["_score"], reverse=True)
    top = scored[:10]

    for job in top:
        seen_ids.add(job["_id"])
    save_seen(seen_ids)

    if not top:
        tg("No new matching jobs found in this scan.")
        return

    sources = list({j["source"] for j in top})
    tg(f"🔍 *{len(top)} new job matches*\nSources: {', '.join(sources)}\nSorted by match score ↓")

    for i, job in enumerate(top, 1):
        tg(format_job(job, i))
        time.sleep(0.3)


# ─── Vercel entry point ───────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        run_scan()
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Done.")

    def log_message(self, format, *args):
        pass
