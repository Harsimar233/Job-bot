"""
Core job scraping logic — used by both webhook and daily scan.
"""
import re, requests, feedparser, hashlib
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime

SCRAPER_KEY = __import__("os").environ.get("SCRAPER_KEY", "")

CUTOFF_DAYS = 7

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RemoteRadar/1.0)"}

# ── Helpers ───────────────────────────────────────────────────────────────────

def jid(url):
    return hashlib.md5(url.encode()).hexdigest()[:12]

def parse_date(s):
    if not s:
        return None
    try:
        return parsedate_to_datetime(s)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        pass
    return None

def is_recent(date_str, days=CUTOFF_DAYS):
    dt = parse_date(date_str)
    if dt is None:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= datetime.now(timezone.utc) - timedelta(days=days)

def fmt_date(s):
    dt = parse_date(s)
    return dt.strftime("%-d %b %Y") if dt else ""

def scrape_url(url, timeout=25, render=False):
    if SCRAPER_KEY:
        p = f"api_key={SCRAPER_KEY}&url={requests.utils.quote(url, safe=':/')}"
        if render:
            p += "&render=true"
        return requests.get(f"http://api.scraperapi.com?{p}", timeout=timeout)
    return requests.get(url, headers=HEADERS, timeout=timeout)

def make_job(title, company, url, source, date="", location="Remote", desc=""):
    return {
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "url": (url or "").strip(),
        "source": source,
        "date": date,
        "location": (location or "Remote").strip(),
        "desc": desc or "",
        "_id": jid(url or title or ""),
    }

# ── Relevance ─────────────────────────────────────────────────────────────────

ROLE_KEYWORDS = [
    "community manager","community lead","community moderator","community mod",
    "community operations","community building","community advocate","community growth",
    "web3 community","crypto community","dao community","nft community",
    "discord moderator","discord mod","telegram moderator","moderator","content moderator",
    "customer support","customer success","support specialist","support agent",
    "support manager","live chat support","help desk",
    "social media manager","social media lead","social media strategist",
    "social media coordinator","social media growth","content creator","content strategist",
    "twitter manager","x manager",
    "marketing manager","marketing lead","growth marketing","growth manager",
    "growth hacker","marketing coordinator","crypto marketing","web3 marketing",
    "blockchain marketing","defi marketing","marketing specialist",
    "performance marketing","digital marketing",
    "kol manager","kol lead","influencer manager","influencer marketing",
    "partnerships manager","partnership lead","bd manager",
    "business development","ecosystem partnerships",
    "ambassador","ambassador program","ambassador lead","ambassador manager",
    "regional ambassador","ecosystem growth",
]

CRYPTO_SIGNALS = [
    "web3","crypto","blockchain","defi","nft","dao","dex","protocol","token",
    "wallet","exchange","binance","coinbase","uniswap","polygon","arbitrum",
    "optimism","solana","ethereum","bitcoin","chainlink","decentralized",
    "on-chain","layer2","layer 2","l2","metaverse","gamefi","yield","staking",
]

EXCLUDES = [
    "engineer","developer","software","solidity","backend","frontend","devops",
    "data scientist","machine learning","accountant","lawyer","designer",
    "mandarin only","chinese speaker required","russian speaker required",
    "native japanese","spanish required","portuguese required","french required",
]

FAKE = [r"post a job", r"browse jobs", r"view all jobs", r"find jobs", r"get hired now"]

def is_relevant(title, desc="", require_crypto=True):
    t = (title + " " + desc).lower()
    if len(title) < 4 or len(title) > 180:
        return False
    if any(re.search(p, title.lower()) for p in FAKE):
        return False
    if any(e in title.lower() for e in EXCLUDES):
        return False
    has_role = any(k in t for k in ROLE_KEYWORDS)
    if not has_role:
        return False
    if require_crypto:
        return any(s in t for s in CRYPTO_SIGNALS)
    return True

def matches_user(job, keywords, location, remote_only):
    """Check if a job matches a user's preferences."""
    t = (job["title"] + " " + job["desc"] + " " + job["company"]).lower()
    loc = job["location"].lower()

    # Keyword match
    kws = [k.strip().lower() for k in keywords.split(",") if k.strip()]
    if kws and not any(k in t for k in kws):
        return False

    # Location match
    if remote_only and "remote" not in loc:
        # Allow jobs with no location specified
        if loc and loc not in ["", "worldwide", "anywhere"]:
            return False

    if location and location.lower() not in ["remote", "worldwide", "any", ""]:
        if location.lower() not in loc and "remote" not in loc:
            return False

    return True

def score(title):
    t = title.lower()
    return min(sum(10 for k in ROLE_KEYWORDS if k in t), 100)

# ── Sources ───────────────────────────────────────────────────────────────────

def scrape_wwr():
    jobs = []
    for cat in ["remote-customer-support-jobs", "remote-marketing-jobs", "all-other-remote-jobs"]:
        try:
            feed = feedparser.parse(f"https://weworkremotely.com/categories/{cat}.rss")
            for e in feed.entries:
                if not is_recent(e.get("published")):
                    continue
                raw = e.get("title", "")
                if " at " in raw:
                    title, company = raw.split(" at ")[0].strip(), raw.split(" at ")[-1].strip()
                elif ": " in raw:
                    company, title = raw.split(": ", 1)[0].strip(), raw.split(": ", 1)[1].strip()
                else:
                    title, company = raw, ""
                desc = e.get("summary", "")
                if is_relevant(title, desc):
                    jobs.append(make_job(title, company, e.get("link",""), "WeWorkRemotely", e.get("published",""), desc=desc))
        except Exception as ex:
            print(f"WWR: {ex}")
    print(f"WWR: {len(jobs)}")
    return jobs

def scrape_remoteok():
    jobs = []
    try:
        r = requests.get("https://remoteok.com/api?tags=community,marketing,crypto,web3,social-media,non-tech",
                         headers=HEADERS, timeout=10)
        for j in r.json()[1:]:
            if not is_recent(j.get("date","")):
                continue
            title = j.get("position","")
            tags = " ".join(j.get("tags",[]))
            desc = j.get("description","")
            if is_relevant(title, tags + " " + desc):
                jobs.append(make_job(title, j.get("company",""), j.get("url",""), "RemoteOK", j.get("date",""), desc=desc))
    except Exception as e:
        print(f"RemoteOK: {e}")
    print(f"RemoteOK: {len(jobs)}")
    return jobs

def scrape_jobicy():
    jobs = []
    seen = set()
    for q in ["community+manager","moderator","customer+support","social+media+manager",
               "ambassador","kol+manager","influencer+marketing","marketing+manager",
               "growth+manager","partnerships+manager"]:
        try:
            r = requests.get(f"https://jobicy.com/api/v2/remote-jobs?count=20&tag={q}",
                             headers=HEADERS, timeout=10)
            for j in r.json().get("jobs",[]):
                if not is_recent(j.get("pubDate","")):
                    continue
                title = j.get("jobTitle","")
                url = j.get("url","")
                desc = j.get("jobDescription","")
                if is_relevant(title, desc) and url not in seen:
                    seen.add(url)
                    jobs.append(make_job(title, j.get("companyName",""), url, "Jobicy", j.get("pubDate",""), desc=desc))
        except Exception as e:
            print(f"Jobicy: {e}")
    print(f"Jobicy: {len(jobs)}")
    return jobs

def scrape_web3career():
    jobs = []
    seen = set()
    for q in ["community-manager","moderator","customer-support","social-media-manager",
               "marketing","ambassador","growth","partnerships"]:
        try:
            r = scrape_url(f"https://web3.career/{q}-jobs")
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup.find_all("h2"):
                title = tag.get_text(strip=True)
                if not is_relevant(title, require_crypto=False):
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
                if link in seen:
                    continue
                seen.add(link)
                company_tag = tag.find_next("h3")
                company = company_tag.get_text(strip=True) if company_tag else ""
                jobs.append(make_job(title, company, link, "Web3.career", date_str))
        except Exception as e:
            print(f"Web3.career: {e}")
    print(f"Web3.career: {len(jobs)}")
    return jobs

GREENHOUSE_COMPANIES = [
    "coinbase","uniswaplabs","chainlink-labs","polygon-labs","arbitrum",
    "optimism-pbc","aave","opensea","consensys","ledger","kraken","gemini",
    "ripple","blockchain-com","bitgo","anchorage","alchemy","metamask",
]

def scrape_greenhouse():
    jobs = []
    seen = set()
    for company in GREENHOUSE_COMPANIES:
        try:
            r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true",
                             headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            for j in r.json().get("jobs",[]):
                title = j.get("title","")
                url = j.get("absolute_url","")
                updated = j.get("updated_at","")
                if not is_recent(updated):
                    continue
                content = j.get("content","")
                if is_relevant(title, content, require_crypto=False) and url not in seen:
                    seen.add(url)
                    loc = j.get("location",{}).get("name","Remote")
                    jobs.append(make_job(title, company.replace("-"," ").title(), url, "Greenhouse", updated, loc, content))
        except Exception as e:
            print(f"Greenhouse {company}: {e}")
    print(f"Greenhouse: {len(jobs)}")
    return jobs

LEVER_COMPANIES = [
    "binance","moonpay","fireblocks","chainalysis","nansen","dune",
    "the-graph","livepeer","filecoin","protocol-labs","near","immutable",
    "sandbox","magic-eden","blur","animoca",
]

def scrape_lever():
    jobs = []
    seen = set()
    for company in LEVER_COMPANIES:
        try:
            r = requests.get(f"https://api.lever.co/v0/postings/{company}?mode=json",
                             headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            for j in r.json():
                title = j.get("text","")
                url = j.get("hostedUrl","")
                created = j.get("createdAt",0)
                date_str = datetime.fromtimestamp(created/1000, tz=timezone.utc).isoformat() if created else ""
                if not is_recent(date_str):
                    continue
                desc = j.get("descriptionPlain","")
                if is_relevant(title, desc, require_crypto=False) and url not in seen:
                    seen.add(url)
                    loc = j.get("categories",{}).get("location","Remote")
                    jobs.append(make_job(title, company.replace("-"," ").title(), url, "Lever", date_str, loc, desc))
        except Exception as e:
            print(f"Lever {company}: {e}")
    print(f"Lever: {len(jobs)}")
    return jobs

def get_all_jobs():
    """Fetch jobs from all sources."""
    all_jobs = []
    for fn in [scrape_wwr, scrape_remoteok, scrape_jobicy, scrape_web3career,
               scrape_greenhouse, scrape_lever]:
        try:
            all_jobs += fn()
        except Exception as e:
            print(f"{fn.__name__} crashed: {e}")

    # Deduplicate by URL
    seen, unique = set(), []
    for j in all_jobs:
        if j["_id"] not in seen and j["url"]:
            seen.add(j["_id"])
            unique.append(j)

    unique.sort(key=lambda j: score(j["title"]), reverse=True)
    print(f"Total unique jobs: {len(unique)}")
    return unique
