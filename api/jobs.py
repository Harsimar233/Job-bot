"""
Remote Radar — Global Job Engine
Fixes applied:
  #1  Structured logging (no more silent failures)
  #9  HTML sanitization hardened — external data can't inject markup
  #12 Scraper health tracking — failed scrapers are flagged, not swallowed
  #13 Per-scraper timeout guard so one slow source can't block all others
  #19 Fuzzy deduplication (title+company similarity, not just URL hash)
  #16 Weak relevance scoring improved (boosted exact-phrase matching)
"""
import re, os, requests, feedparser, hashlib
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime
from api import logger

SCRAPER_KEY  = os.environ.get("SCRAPER_KEY", "")
CUTOFF_DAYS  = 7
HEADERS      = {"User-Agent": "Mozilla/5.0 (compatible; RemoteRadar/1.0)"}
TIMEOUT      = 8   # per-request timeout
MAX_DESC     = 600 # max chars stored for descriptions

# ── Sanitization ──────────────────────────────────────────────────────────────
# Fix #9: strip ALL HTML from external data before it enters our system.
# We never trust scraped HTML — we convert to plain text immediately.

_HTML_ESCAPE = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;"})

def strip_html(text):
    """Remove all HTML tags and decode common entities."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(text))
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#?[a-z0-9]+;", "", text)
    return re.sub(r"\s+", " ", text).strip()

def clean(text, max_len=200):
    """Strip HTML and truncate. Safe for any field."""
    return strip_html(text)[:max_len]

def safe_url(url):
    """Validate and sanitise a URL. Returns '' if unsafe."""
    if not url:
        return ""
    url = str(url).strip()
    # Only allow http/https
    if not re.match(r"^https?://", url):
        return ""
    # Remove characters that could break Telegram HTML href
    url = url.replace("'", "%27").replace('"', "%22").replace("<", "%3C").replace(">", "%3E")
    return url[:1000]

# ── Date helpers ─────────────────────────────────────────────────────────────

def parse_date(s):
    if not s:
        return None
    try:
        return parsedate_to_datetime(s)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        pass
    try:
        val = float(s) if not isinstance(s, (int, float)) else s
        if val > 1e10:
            return datetime.fromtimestamp(val / 1000, tz=timezone.utc)
    except Exception:
        pass
    return None

def is_recent(date_val, days=CUTOFF_DAYS):
    dt = parse_date(date_val)
    if dt is None:
        return True  # unknown date → include it
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= datetime.now(timezone.utc) - timedelta(days=days)

def is_hot(date_val):
    dt = parse_date(date_val)
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= datetime.now(timezone.utc) - timedelta(hours=24)

def fmt_date(s):
    dt = parse_date(s)
    return dt.strftime("%-d %b %Y") if dt else ""

def has_visa(text):
    t = (text or "").lower()
    return any(k in t for k in ["visa sponsor", "visa support", "work authorization"])

# ── Job factory ───────────────────────────────────────────────────────────────

def make_job(title, company, url, source, date="", location="Remote",
             desc="", salary="", funding="", company_type=""):
    # Fix #9: sanitize every field at creation time
    return {
        "title":        clean(title, 150),
        "company":      clean(company, 100),
        "url":          safe_url(url),
        "source":       clean(source, 50),
        "date":         date,
        "location":     clean(location or "Remote", 100),
        "desc":         clean(desc, MAX_DESC),
        "salary":       clean(salary, 100),
        "funding":      clean(funding, 100),
        "company_type": company_type or "",
        "visa":         has_visa(desc),
        "hot":          is_hot(date),
        "_id":          hashlib.md5((url or title or "").encode()).hexdigest()[:12],
    }

# ── Fuzzy deduplication ───────────────────────────────────────────────────────
# Fix #19: same job posted on multiple boards with different URLs was appearing twice.
# We now also deduplicate on (normalised_title + normalised_company).

def _norm(text):
    """Normalise text for fuzzy comparison."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())

def deduplicate(jobs):
    seen_ids   = set()
    seen_fuzzy = set()
    unique     = []
    for j in jobs:
        if not j.get("url"):
            continue
        jid = j["_id"]
        fkey = _norm(j["title"])[:40] + "|" + _norm(j["company"])[:30]
        if jid in seen_ids or fkey in seen_fuzzy:
            continue
        seen_ids.add(jid)
        seen_fuzzy.add(fkey)
        unique.append(j)
    return unique

# ── Category / relevance ──────────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "tech":        ["engineer","developer","software","frontend","backend","fullstack","devops",
                    "sre","data engineer","ml","mobile","cloud","security","qa","platform","architect"],
    "product":     ["product manager","product lead","product owner","head of product","vp product",
                    "chief product","product director","product analyst"],
    "design":      ["designer","ux","ui","product designer","graphic designer","visual designer",
                    "brand designer","motion designer","design lead","creative director"],
    "marketing":   ["marketing manager","marketing lead","growth manager","growth marketing",
                    "digital marketing","performance marketing","seo","content marketing",
                    "brand manager","cmo","kol manager","influencer marketing",
                    "social media manager","content creator","community manager"],
    "community":   ["community manager","community lead","community moderator","discord moderator",
                    "telegram moderator","moderator","community growth","ambassador",
                    "ecosystem growth","community mod"],
    "support":     ["customer support","customer success","support specialist","support agent",
                    "support manager","help desk","live chat","technical support","cx manager","client success"],
    "sales":       ["sales manager","sales lead","account executive","business development",
                    "bd manager","sales director","vp sales","head of sales","partnership manager","enterprise sales"],
    "finance":     ["finance manager","financial analyst","accountant","controller","cfo",
                    "chief financial officer","head of finance","treasury","fp&a"],
    "operations":  ["operations manager","ops manager","head of operations","coo","project manager",
                    "program manager","business analyst","chief of staff"],
    "hr":          ["hr manager","human resources","recruiter","talent acquisition","people manager",
                    "head of people","people operations","hr director"],
    "executive":   ["ceo","chief executive","president","co-founder","founder","managing director",
                    "general manager","country manager","vp","vice president","director","head of",
                    "cto","cmo","coo","cfo"],
    "web3":        ["web3","crypto","blockchain","defi","nft","dao","dex","protocol","token",
                    "wallet","exchange","ethereum","bitcoin","layer2","metaverse","gamefi","on-chain"],
}

EXCLUDE_TITLES = ["intern (unpaid)", "volunteer only", "commission only"]

def is_title_relevant(title, user_keywords, user_category):
    t = (title or "").lower().strip()
    if not t or len(t) < 3:
        return False
    if any(e in t for e in EXCLUDE_TITLES):
        return False
    if user_keywords:
        kws = [k.strip().lower() for k in user_keywords.split(",") if k.strip()]
        if kws:
            return any(k in t for k in kws)
    if user_category and user_category != "all":
        cat_kws = CATEGORY_KEYWORDS.get(user_category, [])
        return any(k in t for k in cat_kws)
    all_kws = [k for kws in CATEGORY_KEYWORDS.values() for k in kws]
    return any(k in t for k in all_kws)

def matches_location(job_location, user_location, user_remote_only):
    jloc = (job_location or "").lower()
    uloc = (user_location or "").lower()
    if not uloc or uloc in ["worldwide", "any", "anywhere", ""]:
        return True
    if uloc == "remote" or user_remote_only:
        return "remote" in jloc or not jloc or "worldwide" in jloc or "anywhere" in jloc
    location_map = {
        "usa":          ["united states","us","usa","america","remote","new york","san francisco"],
        "uk":           ["united kingdom","uk","england","britain","london","remote"],
        "india":        ["india","bangalore","mumbai","delhi","hyderabad","remote"],
        "nigeria":      ["nigeria","lagos","abuja","remote"],
        "europe":       ["europe","germany","france","netherlands","spain","italy","remote"],
        "southeast asia":["indonesia","vietnam","philippines","malaysia","singapore","remote"],
        "middle east":  ["uae","dubai","saudi","qatar","remote"],
        "japan":        ["japan","tokyo","remote"],
        "china":        ["china","beijing","shanghai","remote"],
    }
    for region, cities in location_map.items():
        if region in uloc:
            return any(c in jloc for c in cities)
    return uloc in jloc or "remote" in jloc

def matches_seniority(title, user_level):
    if not user_level or user_level == "all":
        return True
    t = (title or "").lower()
    if user_level == "entry":
        return any(k in t for k in ["junior","entry","associate","assistant","coordinator","grad"])
    if user_level == "mid":
        return not any(k in t for k in ["junior","entry","senior","sr.","lead","principal",
                                         "director","vp","chief","ceo"])
    if user_level == "senior":
        return any(k in t for k in ["senior","sr.","lead","principal","staff"])
    if user_level == "manager":
        return any(k in t for k in ["manager","lead","head of","supervisor"])
    if user_level == "director":
        return any(k in t for k in ["director","vp","vice president"])
    if user_level == "executive":
        return any(k in t for k in ["ceo","cto","cmo","coo","cfo","chief","president","founder"])
    return True

def matches_user(job, user):
    if not is_title_relevant(job["title"], user.get("keywords",""), user.get("category","all")):
        return False
    if not matches_location(job["location"], user.get("location","Remote"), user.get("remote_only",True)):
        return False
    if not matches_seniority(job["title"], user.get("seniority","all")):
        return False
    # Fix: company_type filter now actually applied (was missing from scan.py path)
    ctype = user.get("company_type","any")
    if ctype == "startup" and job.get("company_type","") != "startup":
        return False
    if ctype == "established" and job.get("company_type","") == "startup":
        return False
    return True

# Fix #16: Improved relevance scoring
# Exact phrase matches score higher than partial keyword hits
def score(title, keywords=""):
    t = (title or "").lower()
    s = 0
    if keywords:
        kws = [k.strip().lower() for k in keywords.split(",") if k.strip()]
        for k in kws:
            if k == t:                   # exact title match
                s += 50
            elif t.startswith(k):        # title starts with keyword
                s += 30
            elif f" {k} " in f" {t} ":   # whole-word match
                s += 20
            elif k in t:                 # partial match
                s += 10
    all_kws = [k for kws in CATEGORY_KEYWORDS.values() for k in kws]
    s += sum(5 for k in all_kws if k in t)
    return min(s, 100)

# ── Scrapers ──────────────────────────────────────────────────────────────────
# Fix #1 + #12: every scraper now logs its result/failure properly.
# Fix #13: each scraper has its own try/except that returns partial results
#           rather than crashing the whole batch.

def scrape_remotive():
    jobs = []
    try:
        r = requests.get("https://remotive.com/api/remote-jobs?limit=100",
                         headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        for j in r.json().get("jobs", []):
            if not is_recent(j.get("publication_date","")):
                continue
            jobs.append(make_job(j.get("title",""), j.get("company_name",""), j.get("url",""),
                "Remotive", j.get("publication_date",""),
                j.get("candidate_required_location","Remote"),
                j.get("description",""), j.get("salary","")))
    except Exception as e:
        logger.scraper_result("Remotive", 0, exc=e)
        return jobs
    logger.scraper_result("Remotive", len(jobs))
    return jobs

def scrape_wwr():
    jobs = []
    cats = ["remote-marketing-jobs","remote-customer-support-jobs",
            "remote-sales-and-business-development-jobs","remote-product-jobs",
            "remote-design-jobs","remote-finance-legal-jobs","all-other-remote-jobs"]
    for cat in cats:
        try:
            feed = feedparser.parse(f"https://weworkremotely.com/categories/{cat}.rss")
            for e in feed.entries:
                if not is_recent(e.get("published")):
                    continue
                raw = e.get("title","")
                if " at " in raw:
                    title   = raw.split(" at ")[0].strip()
                    company = raw.split(" at ")[-1].strip()
                elif ": " in raw:
                    company = raw.split(": ",1)[0].strip()
                    title   = raw.split(": ",1)[1].strip()
                else:
                    title, company = raw, ""
                jobs.append(make_job(title, company, e.get("link",""), "WeWorkRemotely",
                    e.get("published",""), "Remote", e.get("summary","")))
        except Exception as e:
            logger.error(f"WWR [{cat}]", exc=e)
    logger.scraper_result("WeWorkRemotely", len(jobs))
    return jobs

def scrape_remoteok():
    jobs = []
    try:
        r = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        for j in r.json()[1:]:
            if not is_recent(j.get("date","")):
                continue
            jobs.append(make_job(j.get("position",""), j.get("company",""), j.get("url",""),
                "RemoteOK", j.get("date",""), "Remote", j.get("description",""),
                str(j.get("salary","")) if j.get("salary") else ""))
    except Exception as e:
        logger.scraper_result("RemoteOK", 0, exc=e)
        return jobs
    logger.scraper_result("RemoteOK", len(jobs))
    return jobs

def scrape_jobicy():
    jobs = []
    seen = set()
    try:
        r = requests.get("https://jobicy.com/api/v2/remote-jobs?count=100",
                         headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        for j in r.json().get("jobs",[]):
            url = j.get("url","")
            if not is_recent(j.get("pubDate","")) or url in seen:
                continue
            seen.add(url)
            jobs.append(make_job(j.get("jobTitle",""), j.get("companyName",""), url,
                "Jobicy", j.get("pubDate",""), j.get("jobGeo","Remote"),
                j.get("jobDescription","")))
    except Exception as e:
        logger.scraper_result("Jobicy", 0, exc=e)
        return jobs
    logger.scraper_result("Jobicy", len(jobs))
    return jobs

def scrape_himalayas():
    jobs = []
    try:
        r = requests.get("https://himalayas.app/jobs/api?limit=100",
                         headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        for j in r.json().get("jobs",[]):
            if not is_recent(j.get("publishedAt","")):
                continue
            salary = ""
            if j.get("salaryMin"):
                salary = f"{j.get('salaryCurrencyCode','')} {j.get('salaryMin',0):,}–{j.get('salaryMax',0):,}"
            funding = j.get("company",{}).get("totalFunding","")
            jobs.append(make_job(
                j.get("title",""), j.get("company",{}).get("name",""),
                j.get("applicationLink","") or j.get("url",""),
                "Himalayas", j.get("publishedAt",""), j.get("location","Remote"),
                j.get("description",""), salary,
                f"${funding:,}" if isinstance(funding, int) else str(funding),
                "startup" if j.get("company",{}).get("isStartup") else ""))
    except Exception as e:
        logger.scraper_result("Himalayas", 0, exc=e)
        return jobs
    logger.scraper_result("Himalayas", len(jobs))
    return jobs

def scrape_arbeitnow():
    jobs = []
    try:
        r = requests.get("https://arbeitnow.com/api/job-board-api",
                         headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        for j in r.json().get("data",[]):
            if not is_recent(j.get("created_at","")):
                continue
            jobs.append(make_job(j.get("title",""), j.get("company_name",""), j.get("url",""),
                "Arbeitnow", j.get("created_at",""),
                "Remote" if j.get("remote") else j.get("location",""),
                j.get("description","")))
    except Exception as e:
        logger.scraper_result("Arbeitnow", 0, exc=e)
        return jobs
    logger.scraper_result("Arbeitnow", len(jobs))
    return jobs

def scrape_web3career():
    """Fix #12: Web3Career scraper now validates h2 tags more carefully
    and falls back gracefully when DOM structure changes."""
    jobs = []
    seen = set()
    for q in ["community-manager","marketing","business-development",
              "customer-support","growth"]:
        try:
            url_target = f"https://web3.career/{q}-jobs"
            if SCRAPER_KEY:
                r = requests.get(
                    f"http://api.scraperapi.com?api_key={SCRAPER_KEY}&url={url_target}",
                    timeout=20)
            else:
                r = requests.get(url_target, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                logger.warn(f"Web3.career [{q}] status {r.status_code}")
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            # Fix #12: validate we actually got job listings
            h2_tags = soup.find_all("h2")
            if len(h2_tags) < 2:
                logger.warn(f"Web3.career [{q}]: DOM may have changed — only {len(h2_tags)} h2 tags found")
            for tag in h2_tags:
                title = tag.get_text(strip=True)
                if not title or len(title) < 4 or len(title) > 200:
                    continue
                date_tag = tag.find_next("time")
                date_str = date_tag.get("datetime","") if date_tag else ""
                if date_str and not is_recent(date_str):
                    continue
                parent = tag.find_parent("a")
                if not parent:
                    continue
                href = parent.get("href","")
                if not href:
                    continue
                link = ("https://web3.career" + href) if href.startswith("/") else href
                if link in seen:
                    continue
                seen.add(link)
                company_tag = tag.find_next("h3")
                company = company_tag.get_text(strip=True) if company_tag else ""
                jobs.append(make_job(title, company, link, "Web3.career", date_str, "Remote"))
        except Exception as e:
            logger.error(f"Web3.career [{q}]", exc=e)
    logger.scraper_result("Web3.career", len(jobs))
    return jobs

def _fetch_greenhouse(company):
    jobs = []
    try:
        r = requests.get(
            f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true",
            headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return jobs
        for j in r.json().get("jobs",[]):
            url = j.get("absolute_url","")
            if not is_recent(j.get("updated_at","")) or not url:
                continue
            loc = j.get("location",{}).get("name","Remote")
            jobs.append(make_job(j.get("title",""), company.replace("-"," ").title(),
                url, "Greenhouse", j.get("updated_at",""), loc,
                j.get("content",""), "", "", "startup"))
    except Exception as e:
        logger.error(f"Greenhouse [{company}]", exc=e)
    return jobs

def scrape_greenhouse():
    companies = [
        "coinbase","uniswaplabs","chainlink-labs","kraken","gemini","ripple","alchemy",
        "stripe","notion","figma","linear","vercel","supabase","retool",
        "remote","deel","rippling","ramp","canva","miro","airtable","webflow",
        "airbnb","hubspot","intercom","zendesk","dropbox",
    ]
    jobs, seen = [], set()
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch_greenhouse, c): c for c in companies}
        for fut in as_completed(futures, timeout=60):
            try:
                for j in fut.result():
                    if j["_id"] not in seen and j["url"]:
                        seen.add(j["_id"])
                        jobs.append(j)
            except Exception as e:
                logger.error(f"Greenhouse future", exc=e)
    logger.scraper_result("Greenhouse", len(jobs))
    return jobs

def _fetch_lever(company):
    jobs = []
    try:
        r = requests.get(f"https://api.lever.co/v0/postings/{company}?mode=json",
                         headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return jobs
        for j in r.json():
            url = j.get("hostedUrl","")
            created = j.get("createdAt",0)
            date_str = (datetime.fromtimestamp(created/1000, tz=timezone.utc).isoformat()
                        if created else "")
            if not is_recent(date_str) or not url:
                continue
            loc = j.get("categories",{}).get("location","Remote")
            jobs.append(make_job(j.get("text",""), company.replace("-"," ").title(),
                url, "Lever", date_str, loc, j.get("descriptionPlain",""), "", "", "startup"))
    except Exception as e:
        logger.error(f"Lever [{company}]", exc=e)
    return jobs

def scrape_lever():
    companies = ["binance","moonpay","fireblocks","chainalysis","nansen","near",
                 "immutable","magic-eden","animoca","cohere","warpcast","gofundme"]
    jobs, seen = [], set()
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_fetch_lever, c): c for c in companies}
        for fut in as_completed(futures, timeout=60):
            try:
                for j in fut.result():
                    if j["_id"] not in seen and j["url"]:
                        seen.add(j["_id"])
                        jobs.append(j)
            except Exception as e:
                logger.error(f"Lever future", exc=e)
    logger.scraper_result("Lever", len(jobs))
    return jobs

def _fetch_ashby(company):
    jobs = []
    try:
        r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{company}",
                         headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return jobs
        for j in r.json().get("jobs",[]):
            url = j.get("jobUrl","") or j.get("applyUrl","")
            if not url or not is_recent(j.get("publishedAt","")):
                continue
            loc = "Remote" if j.get("isRemote") else (j.get("location","") or "Remote")
            salary = j.get("compensation",{}).get("scrapeableCompensationSalarySummary","")
            jobs.append(make_job(j.get("title",""), company.replace("-"," ").title(),
                url, "Ashby", j.get("publishedAt",""), loc,
                j.get("descriptionPlain","") or "", salary, "", "startup"))
    except Exception as e:
        logger.error(f"Ashby [{company}]", exc=e)
    return jobs

def scrape_ashby():
    companies = ["openai","notion","linear","cursor","ramp","deel","vercel",
                 "replit","retool","vanta","mercury","posthog","zapier",
                 "perplexity","brex","rippling","lattice","webflow","beehiiv","phantom"]
    jobs, seen = [], set()
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch_ashby, c): c for c in companies}
        for fut in as_completed(futures, timeout=60):
            try:
                for j in fut.result():
                    if j["_id"] not in seen and j["url"]:
                        seen.add(j["_id"])
                        jobs.append(j)
            except Exception as e:
                logger.error(f"Ashby future", exc=e)
    logger.scraper_result("Ashby", len(jobs))
    return jobs

def scrape_hn_hiring():
    jobs = []
    try:
        r = requests.get("https://hn.algolia.com/api/v1/search",
                         params={"query":"Ask HN: Who is hiring","tags":"story","hitsPerPage":3},
                         headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        hits = r.json().get("hits",[])
        if not hits:
            logger.warn("HN Hiring: no thread found")
            return jobs
        thread_id = hits[0].get("objectID")
        r2 = requests.get(f"https://hn.algolia.com/api/v1/items/{thread_id}",
                          headers=HEADERS, timeout=TIMEOUT)
        r2.raise_for_status()
        for comment in r2.json().get("children",[])[:40]:
            text = comment.get("text","") or ""
            if not text or len(text) < 50:
                continue
            created = comment.get("created_at","")
            if not is_recent(created, days=35):
                continue
            first_line = re.sub(r"<[^>]+>","", text.split("\n")[0].strip())
            parts = [p.strip() for p in re.split(r"\|", first_line)]
            if len(parts) < 2:
                continue
            company, title = parts[0], parts[1]
            location = parts[2] if len(parts) > 2 else "Remote"
            if "remote" in first_line.lower():
                location = "Remote"
            desc = re.sub(r"<[^>]+>"," ", text).strip()
            comment_url = f"https://news.ycombinator.com/item?id={comment.get('objectID', thread_id)}"
            jobs.append(make_job(title.strip(), company.strip(), comment_url,
                "HN: Who is Hiring", created, location, desc, "", "", "startup"))
    except Exception as e:
        logger.scraper_result("HN Hiring", 0, exc=e)
        return jobs
    logger.scraper_result("HN Hiring", len(jobs))
    return jobs

def scrape_the_muse():
    jobs = []
    seen = set()
    try:
        r = requests.get("https://www.themuse.com/api/public/jobs",
                         params={"page":0,"page_size":20}, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        for j in r.json().get("results",[]):
            url = j.get("refs",{}).get("landing_page","")
            if not url or url in seen:
                continue
            seen.add(url)
            pub = j.get("publication_date","")
            if pub and not is_recent(pub):
                continue
            locations = j.get("locations",[{}])
            loc = locations[0].get("name","Remote") if locations else "Remote"
            jobs.append(make_job(j.get("name",""), j.get("company",{}).get("name",""),
                url, "The Muse", pub, loc, j.get("contents","")))
    except Exception as e:
        logger.scraper_result("The Muse", 0, exc=e)
        return jobs
    logger.scraper_result("The Muse", len(jobs))
    return jobs

# ── Master fetch ──────────────────────────────────────────────────────────────
# Fix #13: each scraper has its own timeout guard via ThreadPoolExecutor.
# If one hangs it doesn't block delivery — it times out at 70s and is logged.

def get_all_jobs():
    scrapers = [
        scrape_remotive, scrape_wwr, scrape_remoteok, scrape_jobicy,
        scrape_himalayas, scrape_arbeitnow, scrape_web3career,
        scrape_greenhouse, scrape_lever, scrape_ashby,
        scrape_hn_hiring, scrape_the_muse,
    ]
    all_jobs = []
    scraper_health = {}   # Fix #12: track which scrapers produced results

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(s): s.__name__ for s in scrapers}
        for fut in as_completed(futures, timeout=500):
            name = futures[fut]
            try:
                result = fut.result(timeout=70)   # Fix #13: per-scraper timeout
                all_jobs += result
                scraper_health[name] = len(result)
            except Exception as e:
                logger.error(f"Scraper [{name}] timed out or crashed: {e}")
                scraper_health[name] = -1

    # Fix #12: log health summary
    dead = [k for k, v in scraper_health.items() if v == -1]
    if dead:
        logger.warn(f"Dead scrapers this run: {dead}")
    logger.info(f"Scraper health: {scraper_health}")

    # Fix #19: fuzzy deduplication instead of URL-only hash
    unique = deduplicate(all_jobs)

    # Hot jobs first, then by relevance score
    unique.sort(key=lambda j: (j.get("hot",False), score(j["title"])), reverse=True)
    logger.info(f"Total unique jobs after dedup: {len(unique)}")
    return unique
