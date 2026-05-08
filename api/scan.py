from http.server import BaseHTTPRequestHandler
import os, hashlib, json, requests, feedparser, re

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

# These are page headers / ads, not real job titles
FAKE_TITLE_PATTERNS = [
    "hiring.*talent", "latest.*jobs", "success stories",
    "700-1000", "post a job", "browse jobs", "view all",
    "find jobs", "job board", "get hired",
]

def uid(title, company):
    return hashlib.md5(f"{title}{company}".lower().encode()).hexdigest()[:10]

def is_relevant(text):
    t = text.lower().strip()
    if len(t) < 5 or len(t) > 120:
        return False
    if any(re.search(p, t) for p in FAKE_TITLE_PATTERNS):
        return False
    if any(e in t for e in EXCLUDE):
        return False
    return any(k in t for k in KEYWORDS)

def score(title):
    t = title.lower()
    return min(sum(10 for k in KEYWORDS if k in t), 100)

def scrape_wwr():
    jobs = []
    for cat in ["remote-customer-support-jobs", "remote-marketing-jobs"]:
        try:
            feed = feedparser.parse(f"https://weworkremotely.com/categories/{cat}.rss")
            for e in feed.entries:
                raw_title = e.get("title", "")
                # WWR format: "Company: Job Title at Company"
                # Extract just the job title part
                if " at " in raw_title:
                    title = raw_title.split(" at ")[0].strip()
                    company = raw_title.split(" at ")[-1].strip()
                elif ": " in raw_title:
                    parts = raw_title.split(": ", 1)
                    company = parts[0].strip()
                    title = parts[1].strip() if len(parts) > 1 else raw_title
                else:
                    title = raw_title
                    company = ""
                if is_relevant(title):
                    jobs.append({"title": title, "company": company, "url": e.get("link",""), "source": "WeWorkRemotely"})
        except Exception as ex:
            print(f"WWR error: {ex}")
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
        print(f"RemoteOK error: {e}")
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
            print(f"Jobicy error: {e}")
    return jobs

def scrape_hireweb3():
    jobs = []
    try:
        feed = feedparser.parse("https://www.hireweb3.io/rss")
        print(f"HireWeb3 entries: {len(feed.entries)}")
        for e in feed.entries:
            title = e.get("title","")
            if is_relevant(title):
                jobs.append({"title": title, "company": e.get("author",""), "url": e.get("link",""), "source": "HireWeb3"})
    except Exception as e:
        print(f"HireWeb3 error: {e}")
    return jobs

def scrape_jobstash():
    jobs = []
    try:
        r = requests.get(
            "https://middleware.jobstash.xyz/jobs?page=1&limit=100&order=desc&orderBy=publishedAt",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=15
        )
        data = r.json()
        print(f"JobStash response type: {type(data)}, keys: {list(data.keys()) if isinstance(data, dict) else 'list'}")
        job_list = data.get("data", []) if isinstance(data, dict) else data
        for j in job_list:
            title = j.get("title","") or j.get("role","")
            org = j.get("organization", {})
            company = org.get("name","") if isinstance(org, dict) else j.get("company","")
            url = j.get("url","") or j.get("shortUUID","")
            if url and not url.startswith("http"):
                url = f"https://jobstash.xyz/jobs/{url}"
            if is_relevant(title):
                jobs.append({"title": title, "company": company, "url": url, "source": "JobStash"})
        print(f"JobStash matched: {len(jobs)}")
    except Exception as e:
        print(f"JobStash error: {e}")
    return jobs

def scrape_cryptojobslist():
    jobs = []
    if not SCRAPER_KEY:
        print("No SCRAPER_KEY, skipping CryptoJobsList")
        return jobs
    try:
        from bs4 import BeautifulSoup
        for path in ["/community", "/marketing", "/support"]:
            target = f"https://cryptojobslist.com{path}"
            r = requests.get(f"http://api.scraperapi.com?api_key={SCRAPER_KEY}&url={target}", timeout=25)
            soup = BeautifulSoup(r.text, "html.parser")
            # Look for actual job listing elements
            for tag in soup.find_all("h2"):
                title = tag.get_text(strip=True)
                # Skip if looks like a header/ad
                if not is_relevant(title):
                    continue
                parent = tag.find_parent("a")
                if not parent:
                    continue
                link = "https://cryptojobslist.com" + parent["href"] if parent.get("href","").startswith("/") else parent.get("href", target)
                company_tag = tag.find_next("span")
                company = company_tag.get_text(strip=True) if company_tag else ""
                jobs.append({"title": title, "company": company, "url": link, "source": "CryptoJobsList"})
    except Exception as e:
        print(f"CryptoJobsList error: {e}")
    print(f"CryptoJobsList matched: {len(jobs)}")
    return jobs

def scrape_web3career():
    jobs = []
    if not SCRAPER_KEY:
        return jobs
    for q in ["community-manager", "moderator", "customer-support", "social-media"]:
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
                link = "https://web3.career" + parent["href"] if parent.get("href","").startswith("/") else parent.get("href", target)
                company_tag = tag.find_next("h3")
                company = company_tag.get_text(strip=True) if company_tag else ""
                jobs.append({"title": title, "company": company, "url": link, "source": "Web3.career"})
        except Exception as e:
            print(f"Web3.career error: {e}")
    return jobs

def scrape_remote3():
    jobs = []
    if not SCRAPER_KEY:
        return jobs
    try:
        from bs4 import BeautifulSoup
        for path in ["/community-jobs", "/marketing-jobs", "/support-jobs"]:
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
                link = "https://remote3.co" + parent["href"] if parent.get("href","").startswith("/") else parent.get("href", target)
                jobs.append({"title": title, "company": "", "url": link, "source": "Remote3"})
    except Exception as e:
        print(f"Remote3 error: {e}")
    return jobs

def scrape_cryptocurrencyjobs():
    jobs = []
    if not SCRAPER_KEY:
        return jobs
    try:
        from bs4 import BeautifulSoup
        for path in ["/community", "/marketing", "/support"]:
            target = f"https://cryptocurrencyjobs.co{path}"
            r = requests.get(f"http://api.scraperapi.com?api_key={SCRAPER_KEY}&url={target}", timeout=25)
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup.find_all("h2"):
                title = tag.get_text(strip=True)
                if not is_relevant(title):
                    continue
                parent = tag.find_parent("a")
                if not parent:
                    continue
                link = "https://cryptocurrencyjobs.co" + parent["href"] if parent.get("href","").startswith("/") else parent.get("href", target)
                company_tag = tag.find_next("p")
                company = company_tag.get_text(strip=True) if company_tag else ""
                jobs.append({"title": title, "company": company, "url": link, "source": "CryptocurrencyJobs"})
    except Exception as e:
        print(f"CryptocurrencyJobs error: {e}")
    return jobs

def scrape_ct_google():
    jobs = []
    queries = [
        "site:twitter.com hiring community manager web3",
        "site:twitter.com hiring discord moderator crypto",
        "site:twitter.com web3 community manager job remote",
    ]
    for q in queries:
        try:
            encoded = requests.utils.quote(q)
            feed = feedparser.parse(f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en")
            for e in feed.entries:
                title = e.get("title","")
                if is_relevant(title):
                    jobs.append({"title": title, "company": "via CT", "url": e.get("link",""), "source": "Crypto Twitter"})
        except Exception as e:
            print(f"CT Google error: {e}")
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
    print("--- Starting job scan ---")
    all_jobs += scrape_wwr()
    all_jobs += scrape_remoteok()
    all_jobs += scrape_jobicy()
    all_jobs += scrape_hireweb3()
    all_jobs += scrape_jobstash()
    all_jobs += scrape_cryptojobslist()
    all_jobs += scrape_web3career()
    all_jobs += scrape_remote3()
    all_jobs += scrape_cryptocurrencyjobs()
    all_jobs += scrape_ct_google()

    # Deduplicate
    seen_ids = set()
    new_jobs = []
    for j in all_jobs:
        jid = uid(j["title"], j["company"])
        if jid not in seen_ids:
            new_jobs.append(j)
            seen_ids.add(jid)

    new_jobs.sort(key=lambda j: score(j["title"]), reverse=True)
    sources_found = list(set(j["source"] for j in new_jobs))
    print(f"Total: {len(new_jobs)} jobs from {sources_found}")

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

    sources_str = ", ".join(sources_found)
    send_telegram(f"✅ Done — {min(len(new_jobs),20)} jobs from: {sources_str}")
    return f"sent {len(new_jobs)} jobs"

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        result = run_scan()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(result.encode())
