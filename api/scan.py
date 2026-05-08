import os, hashlib, re, requests, feedparser
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler
from bs4 import BeautifulSoup

BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
CHAT_ID     = os.environ.get("CHAT_ID", "")
SCRAPER_KEY = os.environ.get("SCRAPER_KEY", "")
RUN_MODE    = os.environ.get("RUN_MODE", "full")

KEYWORDS = [
    "community manager","community lead","community moderator",
    "discord moderator","telegram moderator","moderator",
    "customer support","customer success","support specialist",
    "social media manager","social media","content moderator",
    "community growth","web3 community","crypto community",
    "ambassador","community operations","community building",
    "community advocate","dao community","nft community",
]

EXCLUDE = [
    "engineer","developer","software","solidity","backend",
    "frontend","devops","data scientist","machine learning",
    "accountant","lawyer","designer","staff engineer",
]

FAKE_PATTERNS = [
    r"hiring.*talent", r"latest.*jobs", r"success stor",
    r"^\d+[-–]\d+/month", r"post a job", r"browse jobs",
    r"view all", r"find jobs", r"job board", r"get hired",
]

def uid(title, company):
    return hashlib.md5(f"{title}{company}".lower().encode()).hexdigest()[:10]

def is_relevant(text):
    t = text.lower().strip()
    if len(t) < 6 or len(t) > 120:
        return False
    if any(re.search(p, t) for p in FAKE_PATTERNS):
        return False
    if any(e in t for e in EXCLUDE):
        return False
    return any(k in t for k in KEYWORDS)

def score(title):
    t = title.lower()
    return min(sum(10 for k in KEYWORDS if k in t), 100)

def scrape_url(url, timeout=25, render=False):
    if SCRAPER_KEY:
        params = f"api_key={SCRAPER_KEY}&url={requests.utils.quote(url, safe=':/')}"
        if render:
            params += "&render=true"
        return requests.get(f"http://api.scraperapi.com?{params}", timeout=timeout)
    return requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)


# ── SOURCES ───────────────────────────────────────────────────────────────────

def scrape_wwr():
    jobs = []
    for cat in ["remote-customer-support-jobs", "remote-marketing-jobs"]:
        try:
            feed = feedparser.parse(f"https://weworkremotely.com/categories/{cat}.rss")
            for e in feed.entries:
                raw = e.get("title", "")
                if " at " in raw:
                    title, company = raw.split(" at ")[0].strip(), raw.split(" at ")[-1].strip()
                elif ": " in raw:
                    parts = raw.split(": ", 1)
                    company, title = parts[0].strip(), parts[1].strip()
                else:
                    title, company = raw, ""
                if is_relevant(title):
                    jobs.append({"title": title, "company": company, "url": e.get("link",""), "source": "WeWorkRemotely"})
        except Exception as ex:
            print(f"WWR: {ex}")
    print(f"WWR: {len(jobs)}")
    return jobs

def scrape_remoteok():
    jobs = []
    try:
        r = requests.get("https://remoteok.com/api", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        for j in r.json()[1:]:
            title = j.get("position", "")
            tags  = " ".join(j.get("tags", []))
            if is_relevant(title) or is_relevant(tags):
                jobs.append({"title": title, "company": j.get("company",""), "url": j.get("url",""), "source": "RemoteOK"})
    except Exception as e:
        print(f"RemoteOK: {e}")
    print(f"RemoteOK: {len(jobs)}")
    return jobs

def scrape_jobicy():
    jobs = []
    for q in ["community+manager","moderator","customer+support","social+media+manager","ambassador"]:
        try:
            r = requests.get(f"https://jobicy.com/api/v2/remote-jobs?count=20&tag={q}", headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
            for j in r.json().get("jobs",[]):
                title = j.get("jobTitle","")
                if is_relevant(title):
                    jobs.append({"title": title, "company": j.get("companyName",""), "url": j.get("url",""), "source": "Jobicy"})
        except Exception as e:
            print(f"Jobicy: {e}")
    print(f"Jobicy: {len(jobs)}")
    return jobs

def scrape_web3career():
    jobs = []
    for q in ["community-manager", "moderator", "customer-support", "social-media-manager"]:
        try:
            r = scrape_url(f"https://web3.career/{q}-jobs")
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup.find_all("h2"):
                title = tag.get_text(strip=True)
                if not is_relevant(title):
                    continue
                parent = tag.find_parent("a")
                if not parent:
                    continue
                href = parent.get("href","")
                link = ("https://web3.career" + href) if href.startswith("/") else href
                company_tag = tag.find_next("h3")
                company = company_tag.get_text(strip=True) if company_tag else ""
                jobs.append({"title": title, "company": company, "url": link, "source": "Web3.career"})
        except Exception as e:
            print(f"Web3.career: {e}")
    print(f"Web3.career: {len(jobs)}")
    return jobs

def scrape_cryptojobslist():
    jobs = []
    for path in ["/community", "/marketing", "/support"]:
        try:
            r = scrape_url(f"https://cryptojobslist.com{path}")
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup.find_all("h2"):
                title = tag.get_text(strip=True)
                if not is_relevant(title):
                    continue
                parent = tag.find_parent("a")
                if not parent:
                    continue
                href = parent.get("href","")
                link = ("https://cryptojobslist.com" + href) if href.startswith("/") else href
                company_tag = tag.find_next("span")
                company = company_tag.get_text(strip=True) if company_tag else ""
                jobs.append({"title": title, "company": company, "url": link, "source": "CryptoJobsList"})
        except Exception as e:
            print(f"CryptoJobsList: {e}")
    print(f"CryptoJobsList: {len(jobs)}")
    return jobs

def scrape_cryptocurrencyjobs():
    jobs = []
    for target in [
        "https://cryptocurrencyjobs.co/community/",
        "https://cryptocurrencyjobs.co/marketing/",
        "https://cryptocurrencyjobs.co/support/",
    ]:
        try:
            r = scrape_url(target, render=True)
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup.find_all(["h2","h3"]):
                title = tag.get_text(strip=True)
                if not is_relevant(title):
                    continue
                parent = tag.find_parent("a")
                if not parent:
                    continue
                href = parent.get("href","")
                link = ("https://cryptocurrencyjobs.co" + href) if href.startswith("/") else href
                company_tag = tag.find_next(["span","p"])
                company = company_tag.get_text(strip=True) if company_tag else ""
                jobs.append({"title": title, "company": company, "url": link, "source": "CryptocurrencyJobs"})
        except Exception as e:
            print(f"CryptocurrencyJobs: {e}")
    print(f"CryptocurrencyJobs: {len(jobs)}")
    return jobs


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        return
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=10
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def run_scan():
    all_jobs = []
    all_jobs += scrape_wwr()
    all_jobs += scrape_remoteok()
    all_jobs += scrape_jobicy()
    all_jobs += scrape_web3career()
    all_jobs += scrape_cryptojobslist()
    all_jobs += scrape_cryptocurrencyjobs()

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    seen, new_jobs = set(), []
    for j in all_jobs:
        jid = uid(j["title"], j["company"])
        if jid not in seen:
            new_jobs.append(j)
            seen.add(jid)

    new_jobs.sort(key=lambda j: score(j["title"]), reverse=True)
    sources = list(set(j["source"] for j in new_jobs))
    print(f"Total: {len(new_jobs)} jobs | Sources: {sources}")

    if not new_jobs:
        send_telegram("No new matching jobs found.")
        return "no jobs"

    send_telegram(f"🔍 <b>{min(len(new_jobs),20)} new job matches</b>\nSources: {', '.join(sources)}")

    for j in new_jobs[:20]:
        send_telegram(
            f"💼 <b>{j['title']}</b>\n"
            f"🏢 {j['company']}\n"
            f"🔗 <a href='{j['url']}'>Apply Now</a>\n"
            f"📌 via {j['source']}"
        )

    return f"sent {len(new_jobs)} jobs"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        result = run_scan()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(result.encode())

if __name__ == "__main__":
    run_scan()
