import os, re, hashlib, json, requests, feedparser

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID   = os.environ.get("CHAT_ID", "")
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

SEEN_FILE = "/tmp/seen.json"


def load_seen():
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except:
        return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen)[-500:], f)


def uid(title, company):
    return hashlib.md5(f"{title}{company}".lower().encode()).hexdigest()[:10]


def is_relevant(title):
    t = title.lower()
    if any(e in t for e in EXCLUDE):
        return False
    return any(k in t for k in KEYWORDS)


def score(title):
    t = title.lower()
    s = 0
    for k in KEYWORDS:
        if k in t:
            s += 10
    return min(s, 100)


def scrape_remoteok():
    jobs = []
    try:
        r = requests.get("https://remoteok.com/api", headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        data = r.json()
        for j in data[1:]:
            title = j.get("position", "")
            company = j.get("company", "")
            url = j.get("url", "")
            tags = " ".join(j.get("tags", []))
            if is_relevant(title) or is_relevant(tags):
                jobs.append({"title": title, "company": company, "url": url, "source": "RemoteOK"})
    except Exception as e:
        print(f"RemoteOK error: {e}")
    return jobs


def scrape_wwr():
    jobs = []
    feeds = [
        "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
        "https://weworkremotely.com/categories/remote-marketing-jobs.rss",
        "https://weworkremotely.com/categories/remote-sales-jobs.rss",
    ]
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for e in feed.entries:
                title = e.get("title", "")
                company = e.get("author", "")
                url = e.get("link", "")
                if is_relevant(title):
                    jobs.append({"title": title, "company": company, "url": url, "source": "WeWorkRemotely"})
        except Exception as ex:
            print(f"WWR error: {ex}")
    return jobs


def scrape_jobicy():
    jobs = []
    searches = ["community+manager", "moderator", "customer+support", "social+media+manager", "ambassador"]
    for q in searches:
        try:
            r = requests.get(
                f"https://jobicy.com/api/v2/remote-jobs?count=20&tag={q}",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15
            )
            data = r.json()
            for j in data.get("jobs", []):
                title = j.get("jobTitle", "")
                company = j.get("companyName", "")
                url = j.get("url", "")
                if is_relevant(title):
                    jobs.append({"title": title, "company": company, "url": url, "source": "Jobicy"})
        except Exception as e:
            print(f"Jobicy error: {e}")
    return jobs


def scrape_cryptojobslist():
    jobs = []
    if not SCRAPER_KEY:
        return jobs
    try:
        target = "https://cryptojobslist.com/community"
        url = f"http://api.scraperapi.com?api_key={SCRAPER_KEY}&url={target}"
        r = requests.get(url, timeout=30)
        from bs4 import BeautifulSoup
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
        print(f"CryptoJobsList error: {e}")
    return jobs


def scrape_web3career():
    jobs = []
    if not SCRAPER_KEY:
        return jobs
    searches = ["community-manager", "moderator", "customer-support", "social-media"]
    for q in searches:
        try:
            target = f"https://web3.career/{q}-jobs"
            url = f"http://api.scraperapi.com?api_key={SCRAPER_KEY}&url={target}"
            r = requests.get(url, timeout=30)
            from bs4 import BeautifulSoup
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
            print(f"Web3.career error: {e}")
    return jobs


def scrape_indeed_rss():
    jobs = []
    searches = [
        "community+manager+web3",
        "discord+moderator+crypto",
        "customer+support+web3",
        "social+media+manager+crypto",
        "community+manager+remote",
    ]
    for q in searches:
        try:
            url = f"https://www.indeed.com/rss?q={q}&l=remote&sort=date"
            feed = feedparser.parse(url)
            for e in feed.entries:
                title = e.get("title", "")
                company = e.get("author", "")
                link = e.get("link", "")
                if is_relevant(title):
                    jobs.append({"title": title, "company": company, "url": link, "source": "Indeed"})
        except Exception as ex:
            print(f"Indeed error: {ex}")
    return jobs


def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        print("No bot token/chat id")
        return
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=10
    )


def main():
    seen = load_seen()
    all_jobs = []

    print("Scraping RemoteOK...")
    all_jobs += scrape_remoteok()

    print("Scraping WeWorkRemotely...")
    all_jobs += scrape_wwr()

    print("Scraping Jobicy...")
    all_jobs += scrape_jobicy()

    print("Scraping Indeed RSS...")
    all_jobs += scrape_indeed_rss()

    print("Scraping CryptoJobsList...")
    all_jobs += scrape_cryptojobslist()

    print("Scraping Web3.career...")
    all_jobs += scrape_web3career()

    # Deduplicate
    new_jobs = []
    new_ids = set()
    for j in all_jobs:
        jid = uid(j["title"], j["company"])
        if jid not in seen and jid not in new_ids:
            new_jobs.append(j)
            new_ids.add(jid)

    # Sort by score
    new_jobs.sort(key=lambda j: score(j["title"]), reverse=True)

    print(f"Found {len(new_jobs)} new jobs")

    if not new_jobs:
        send_telegram("✅ Job scan complete — no new matching jobs found.")
        return

    # Send top 15
    for j in new_jobs[:15]:
        msg = (
            f"💼 <b>{j['title']}</b>\n"
            f"🏢 {j['company']}\n"
            f"🔗 <a href='{j['url']}'>Apply Now</a>\n"
            f"📌 via {j['source']}"
        )
        send_telegram(msg)

    send_telegram(f"✅ Scan done — sent {min(len(new_jobs), 15)} new jobs!")
    seen.update(new_ids)
    save_seen(seen)


if __name__ == "__main__":
    main()
