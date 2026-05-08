from http.server import BaseHTTPRequestHandler
import os, hashlib, re, requests, feedparser

BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
CHAT_ID     = os.environ.get("CHAT_ID", "")
SCRAPER_KEY = os.environ.get("SCRAPER_KEY", "")

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

# ── WWR ─────────────────────────────────────────────────────────────────────
def scrape_wwr():
    jobs = []
    for cat in ["remote-customer-support-jobs", "remote-marketing-jobs"]:
        try:
            feed = feedparser.parse(f"https://weworkremotely.com/categories/{cat}.rss")
            for e in feed.entries:
                raw = e.get("title", "")
                if " at " in raw:
                    title   = raw.split(" at ")[0].strip()
                    company = raw.split(" at ")[-1].strip()
                elif ": " in raw:
                    parts   = raw.split(": ", 1)
                    company = parts[0].strip()
                    title   = parts[1].strip()
                else:
                    title, company = raw, ""
                if is_relevant(title):
                    jobs.append({"title": title, "company": company, "url": e.get("link",""), "source": "WeWorkRemotely"})
        except Exception as ex:
            print(f"WWR: {ex}")
    return jobs

# ── RemoteOK ────────────────────────────────────────────────────────────────
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
    return jobs

# ── Jobicy API ───────────────────────────────────────────────────────────────
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
    return jobs

# ── Crypto.jobs RSS ──────────────────────────────────────────────────────────
def scrape_cryptodotjobs():
    jobs = []
    try:
        feed = feedparser.parse("https://crypto.jobs/jobs.rss")
        print(f"crypto.jobs entries: {len(feed.entries)}")
        for e in feed.entries:
            title   = e.get("title","")
            company = e.get("author","") or e.get("dc_creator","")
            if is_relevant(title):
                jobs.append({"title": title, "company": company, "url": e.get("link",""), "source": "crypto.jobs"})
    except Exception as ex:
        print(f"crypto.jobs: {ex}")
    return jobs

# ── CryptocurrencyJobs RSS ───────────────────────────────────────────────────
def scrape_cryptocurrencyjobs_rss():
    jobs = []
    try:
        feed = feedparser.parse("https://cryptocurrencyjobs.co/feed/")
        print(f"CryptocurrencyJobs entries: {len(feed.entries)}")
        for e in feed.entries:
            title   = e.get("title","")
            company = e.get("author","")
            if is_relevant(title):
                jobs.append({"title": title, "company": company, "url": e.get("link",""), "source": "CryptocurrencyJobs"})
    except Exception as ex:
        print(f"CryptocurrencyJobs: {ex}")
    return jobs

# ── CryptoJobsList scrape ────────────────────────────────────────────────────
def scrape_cryptojobslist():
    jobs = []
    if not SCRAPER_KEY:
        return jobs
    try:
        from bs4 import BeautifulSoup
        for path in ["/community", "/marketing", "/support"]:
            target = f"https://cryptojobslist.com{path}"
            r = requests.get(f"http://api.scraperapi.com?api_key={SCRAPER_KEY}&url={target}", timeout=25)
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
    return jobs

# ── Web3.career scrape ───────────────────────────────────────────────────────
def scrape_web3career():
    jobs = []
    if not SCRAPER_KEY:
        return jobs
    for q in ["community-manager", "moderator", "customer-support", "social-media-manager"]:
        try:
            from bs4 import BeautifulSoup
            target = f"https://web3.career/{q}-jobs"
            r = requests.get(f"http://api.scraperapi.com?api_key={SCRAPER_KEY}&url={target}", timeout=25)
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
    return jobs

# ── Remote3 scrape ───────────────────────────────────────────────────────────
def scrape_remote3():
    jobs = []
    if not SCRAPER_KEY:
        return jobs
    for path in ["/community-jobs", "/marketing-jobs", "/support-jobs"]:
        try:
            from bs4 import BeautifulSoup
            target = f"https://remote3.co{path}"
            r = requests.get(f"http://api.scraperapi.com?api_key={SCRAPER_KEY}&url={target}", timeout=25)
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup.find_all(["h2","h3"]):
                title = tag.get_text(strip=True)
                if not is_relevant(title):
                    continue
                parent = tag.find_parent("a")
                if not parent:
                    continue
                href = parent.get("href","")
                link = ("https://remote3.co" + href) if href.startswith("/") else href
                jobs.append({"title": title, "company": "", "url": link, "source": "Remote3"})
        except Exception as e:
            print(f"Remote3: {e}")
    return jobs

# ── Crypto Twitter via Google RSS ────────────────────────────────────────────
def scrape_ct_google():
    jobs = []
    for q in ["site:twitter.com hiring community manager web3",
              "site:twitter.com hiring discord moderator crypto"]:
        try:
            enc = requests.utils.quote(q)
            feed = feedparser.parse(f"https://news.google.com/rss/search?q={enc}&hl=en-US&gl=US&ceid=US:en")
            for e in feed.entries:
                title = e.get("title","")
                if is_relevant(title):
                    jobs.append({"title": title, "company": "CT", "url": e.get("link",""), "source": "Crypto Twitter"})
        except Exception as e:
            print(f"CT: {e}")
    return jobs

# ── Telegram sender ──────────────────────────────────────────────────────────
def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        return
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=10
    )

# ── Main ─────────────────────────────────────────────────────────────────────
def run_scan():
    all_jobs = []
    all_jobs += scrape_wwr()
    all_jobs += scrape_remoteok()
    all_jobs += scrape_jobicy()
    all_jobs += scrape_cryptodotjobs()
    all_jobs += scrape_cryptocurrencyjobs_rss()
    all_jobs += scrape_cryptojobslist()
    all_jobs += scrape_web3career()
    all_jobs += scrape_remote3()
    all_jobs += scrape_ct_google()

    # Deduplicate by title+company hash
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
        send_telegram("✅ Scan done — no new matching jobs found.")
        return "no jobs"

    for j in new_jobs[:20]:
        send_telegram(
            f"💼 <b>{j['title']}</b>\n"
            f"🏢 {j['company']}\n"
            f"🔗 <a href='{j['url']}'>Apply Now</a>\n"
            f"📌 via {j['source']}"
        )

    send_telegram(f"✅ Done — {min(len(new_jobs),20)} jobs from: {', '.join(sources)}")
    return f"sent {len(new_jobs)} jobs"

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        result = run_scan()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(result.encode())
