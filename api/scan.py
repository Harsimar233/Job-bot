from http.server import BaseHTTPRequestHandler
import os, hashlib, json, requests, feedparser

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
]

EXCLUDE = [
    "engineer","developer","software","solidity","backend",
    "frontend","devops","data scientist","machine learning",
    "accountant","lawyer","designer","staff engineer",
]

def uid(title, company):
    return hashlib.md5(f"{title}{company}".lower().encode()).hexdigest()[:10]

def is_relevant(title):
    t = title.lower()
    if any(e in t for e in EXCLUDE):
        return False
    return any(k in t for k in KEYWORDS)

def score(title):
    t = title.lower()
    s = sum(10 for k in KEYWORDS if k in t)
    return min(s, 100)

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

def scrape_wwr():
    jobs = []
    for cat in ["remote-customer-support-jobs", "remote-marketing-jobs"]:
        try:
            feed = feedparser.parse(f"https://weworkremotely.com/categories/{cat}.rss")
            for e in feed.entries:
                title = e.get("title","")
                if is_relevant(title):
                    jobs.append({"title": title, "company": e.get("author",""), "url": e.get("link",""), "source": "WeWorkRemotely"})
        except Exception as ex:
            print(f"WWR: {ex}")
    return jobs

def scrape_jobicy():
    jobs = []
    for q in ["community+manager","moderator","customer+support","social+media+manager"]:
        try:
            r = requests.get(f"https://jobicy.com/api/v2/remote-jobs?count=20&tag={q}", headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
            for j in r.json().get("jobs",[]):
                title = j.get("jobTitle","")
                if is_relevant(title):
                    jobs.append({"title": title, "company": j.get("companyName",""), "url": j.get("url",""), "source": "Jobicy"})
        except Exception as e:
            print(f"Jobicy: {e}")
    return jobs

def scrape_cryptojobslist():
    jobs = []
    if not SCRAPER_KEY:
        return jobs
    try:
        from bs4 import BeautifulSoup
        target = "https://cryptojobslist.com/community"
        r = requests.get(f"http://api.scraperapi.com?api_key={SCRAPER_KEY}&url={target}", timeout=25)
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup.find_all("h2"):
            title = tag.get_text(strip=True)
            parent = tag.find_parent("a")
            link = "https://cryptojobslist.com" + parent["href"] if parent and parent.get("href") else target
            company_tag = tag.find_next("span")
            company = company_tag.get_text(strip=True) if company_tag else ""
            if is_relevant(title):
                jobs.append({"title": title, "company": company, "url": link, "source": "CryptoJobsList"})
    except Exception as e:
        print(f"CryptoJobsList: {e}")
    return jobs

def scrape_web3career():
    jobs = []
    if not SCRAPER_KEY:
        return jobs
    for q in ["community-manager","moderator","customer-support"]:
        try:
            from bs4 import BeautifulSoup
            target = f"https://web3.career/{q}-jobs"
            r = requests.get(f"http://api.scraperapi.com?api_key={SCRAPER_KEY}&url={target}", timeout=25)
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup.find_all("h2"):
                title = tag.get_text(strip=True)
                parent = tag.find_parent("a")
                link = "https://web3.career" + parent["href"] if parent and parent.get("href") else target
                company_tag = tag.find_next("h3")
                company = company_tag.get_text(strip=True) if company_tag else ""
                if is_relevant(title):
                    jobs.append({"title": title, "company": company, "url": link, "source": "Web3.career"})
        except Exception as e:
            print(f"Web3.career: {e}")
    return jobs

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        return
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=10
    )

def run_scan():
    all_jobs = []
    all_jobs += scrape_wwr()
    all_jobs += scrape_remoteok()
    all_jobs += scrape_jobicy()
    all_jobs += scrape_cryptojobslist()
    all_jobs += scrape_web3career()

    # Deduplicate
    seen_ids = set()
    new_jobs = []
    for j in all_jobs:
        jid = uid(j["title"], j["company"])
        if jid not in seen_ids:
            new_jobs.append(j)
            seen_ids.add(jid)

    new_jobs.sort(key=lambda j: score(j["title"]), reverse=True)

    if not new_jobs:
        send_telegram("✅ Scan done — no new matching jobs found.")
        return "no jobs"

    for j in new_jobs[:15]:
        send_telegram(
            f"💼 <b>{j['title']}</b>\n"
            f"🏢 {j['company']}\n"
            f"🔗 <a href='{j['url']}'>Apply Now</a>\n"
            f"📌 via {j['source']}"
        )

    send_telegram(f"✅ Done — sent {min(len(new_jobs),15)} jobs!")
    return f"sent {len(new_jobs)} jobs"

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        result = run_scan()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(result.encode())
