import os, hashlib, re, requests, feedparser
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime

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
    "mandarin","chinese speaker","native chinese",
    "russian speaker","native russian","native japanese",
]

FAKE_PATTERNS = [
    r"hiring.*talent", r"latest.*jobs", r"success stor",
    r"post a job", r"browse jobs", r"view all",
    r"find jobs", r"job board", r"get hired",
]

CUTOFF_DAYS = 7

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

def parse_date(date_str):
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        pass
    return None

def is_recent(date_str, days=CUTOFF_DAYS):
    dt = parse_date(date_str)
    if dt is None:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return dt >= cutoff

def fmt_date(date_str):
    dt = parse_date(date_str)
    if not dt:
        return ""
    return dt.strftime("%-d %b %Y")

def scrape_url(url, timeout=25, render=False):
    if SCRAPER_KEY:
        params = f"api_key={SCRAPER_KEY}&url={requests.utils.quote(url, safe=':/')}"
        if render:
            params += "&render=true"
        return requests.get(f"http://api.scraperapi.com?{params}", timeout=timeout)
    return requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)


# ── SOURCE 1: WeWorkRemotely ──────────────────────────────────────────────────

def scrape_wwr():
    jobs = []
    for cat in ["remote-customer-support-jobs", "remote-marketing-jobs"]:
        try:
            feed = feedparser.parse(f"https://weworkremotely.com/categories/{cat}.rss")
            for e in feed.entries:
                if not is_recent(e.get("published")):
                    continue
                raw = e.get("title", "")
                if " at " in raw:
                    title, company = raw.split(" at ")[0].strip(), raw.split(" at ")[-1].strip()
                elif ": " in raw:
                    parts = raw.split(": ", 1)
                    company, title = parts[0].strip(), parts[1].strip()
                else:
                    title, company = raw, ""
                if is_relevant(title):
                    jobs.append({"title": title, "company": company, "url": e.get("link",""), "source": "WeWorkRemotely", "date": e.get("published","")})
        except Exception as ex:
            print(f"WWR error: {ex}")
    print(f"WWR: {len(jobs)}")
    return jobs


# ── SOURCE 2: RemoteOK ────────────────────────────────────────────────────────

def scrape_remoteok():
    jobs = []
    try:
        r = requests.get("https://remoteok.com/api", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        for j in r.json()[1:]:
            date_str = j.get("date", "")
            if not is_recent(date_str):
                continue
            title = j.get("position", "")
            tags  = " ".join(j.get("tags", []))
            if is_relevant(title) or is_relevant(tags):
                jobs.append({"title": title, "company": j.get("company",""), "url": j.get("url",""), "source": "RemoteOK", "date": date_str})
    except Exception as e:
        print(f"RemoteOK error: {e}")
    print(f"RemoteOK: {len(jobs)}")
    return jobs


# ── SOURCE 3: Jobicy API ──────────────────────────────────────────────────────

def scrape_jobicy():
    jobs = []
    for q in ["community+manager","moderator","customer+support","social+media+manager","ambassador"]:
        try:
            r = requests.get(f"https://jobicy.com/api/v2/remote-jobs?count=20&tag={q}", headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
            for j in r.json().get("jobs",[]):
                if not is_recent(j.get("pubDate","")):
                    continue
                title = j.get("jobTitle","")
                if is_relevant(title):
                    jobs.append({"title": title, "company": j.get("companyName",""), "url": j.get("url",""), "source": "Jobicy", "date": j.get("pubDate","")})
        except Exception as e:
            print(f"Jobicy error: {e}")
    print(f"Jobicy: {len(jobs)}")
    return jobs


# ── SOURCE 4: Web3.career ─────────────────────────────────────────────────────

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
                date_tag = tag.find_next("time")
                date_str = date_tag.get("datetime","") if date_tag else ""
                if date_str and not is_recent(date_str):
                    continue
                parent = tag.find_parent("a")
                if not parent:
                    continue
                href = parent.get("href","")
                link = ("https://web3.career" + href) if href.startswith("/") else href
                company_tag = tag.find_next("h3")
                company = company_tag.get_text(strip=True) if company_tag else ""
                jobs.append({"title": title, "company": company, "url": link, "source": "Web3.career", "date": date_str})
        except Exception as e:
            print(f"Web3.career error: {e}")
    print(f"Web3.career: {len(jobs)}")
    return jobs


# ── SOURCE 5: Indeed RSS ──────────────────────────────────────────────────────

def scrape_indeed():
    jobs = []
    seen = set()
    queries = [
        "web3+community+manager+remote",
        "crypto+community+manager+remote",
        "dao+community+manager+remote",
        "crypto+discord+moderator+remote",
        "web3+customer+support+remote",
        "crypto+social+media+manager+remote",
    ]
    for q in queries:
        try:
            feed = feedparser.parse(f"https://www.indeed.com/rss?q={q}&sort=date")
            for e in feed.entries:
                if not is_recent(e.get("published","")):
                    continue
                link = e.get("link","")
                if not link or link in seen:
                    continue
                title = e.get("title","")
                if not is_relevant(title):
                    continue
                seen.add(link)
                company = e.get("source", {}).get("value","") if isinstance(e.get("source"), dict) else ""
                jobs.append({"title": title, "company": company, "url": link, "source": "Indeed", "date": e.get("published","")})
        except Exception as e:
            print(f"Indeed error: {e}")
    print(f"Indeed: {len(jobs)}")
    return jobs


# ── SOURCE 6: crypto.jobs ─────────────────────────────────────────────────────

def scrape_cryptodotjobs():
    jobs = []
    for path in [
        "/jobs?category=community-manager",
        "/jobs?category=customer-support",
        "/jobs?category=marketing",
    ]:
        try:
            r = scrape_url(f"https://crypto.jobs{path}", render=True, timeout=45)
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup.find_all(["h2","h3"]):
                title = tag.get_text(strip=True)
                if not is_relevant(title):
                    continue
                date_tag = tag.find_next("time")
                date_str = date_tag.get("datetime","") if date_tag else ""
                if date_str and not is_recent(date_str):
                    continue
                parent = tag.find_parent("a")
                if not parent:
                    continue
                href = parent.get("href","")
                link = ("https://crypto.jobs" + href) if href.startswith("/") else href
                company_tag = tag.find_next(["span","p","h4"])
                company = company_tag.get_text(strip=True) if company_tag else ""
                jobs.append({"title": title, "company": company, "url": link, "source": "crypto.jobs", "date": date_str})
        except Exception as e:
            print(f"crypto.jobs error: {e}")
    print(f"crypto.jobs: {len(jobs)}")
    return jobs


# ── SOURCE 7: remote3.co ──────────────────────────────────────────────────────

def scrape_remote3():
    jobs = []
    for path in [
        "/jobs?tag=community-manager",
        "/jobs?tag=customer-support",
        "/jobs?tag=social-media",
        "/jobs?tag=moderator",
    ]:
        try:
            r = scrape_url(f"https://remote3.co{path}", render=True, timeout=45)
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup.find_all(["h2","h3"]):
                title = tag.get_text(strip=True)
                if not is_relevant(title):
                    continue
                date_tag = tag.find_next("time")
                date_str = date_tag.get("datetime","") if date_tag else ""
                if date_str and not is_recent(date_str):
                    continue
                parent = tag.find_parent("a")
                if not parent:
                    continue
                href = parent.get("href","")
                link = ("https://remote3.co" + href) if href.startswith("/") else href
                company_tag = tag.find_next(["span","p"])
                company = company_tag.get_text(strip=True) if company_tag else ""
                jobs.append({"title": title, "company": company, "url": link, "source": "Remote3", "date": date_str})
        except Exception as e:
            print(f"Remote3 error: {e}")
    print(f"Remote3: {len(jobs)}")
    return jobs


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        print("Missing BOT_TOKEN or CHAT_ID")
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
    all_jobs += scrape_indeed()
    all_jobs += scrape_cryptodotjobs()
    all_jobs += scrape_remote3()

    seen, new_jobs = set(), []
    for j in all_jobs:
        jid = uid(j["title"], j["company"])
        if jid not in seen:
            new_jobs.append(j)
            seen.add(jid)

    new_jobs.sort(key=lambda j: score(j["title"]), reverse=True)
    sources = list(set(j["source"] for j in new_jobs))
    print(f"Total after date filter: {len(new_jobs)} | Sources: {sources}")

    if not new_jobs:
        send_telegram("No new matching jobs from the last 7 days.")
        return "no jobs"

    send_telegram(f"🔍 <b>{min(len(new_jobs),20)} jobs from the last 7 days</b>\nSources: {', '.join(sources)}")

    for j in new_jobs[:20]:
        date_label = f"\n📅 {fmt_date(j.get('date',''))}" if j.get("date") else ""
        send_telegram(
            f"💼 <b>{j['title']}</b>\n"
            f"🏢 {j['company']}{date_label}\n"
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
