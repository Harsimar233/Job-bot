"""
Remote Radar — Global Job Engine with parallel scraping.
All sources run simultaneously — finishes in under 3 minutes.
"""
import re, os, requests, feedparser, hashlib
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime

SCRAPER_KEY = os.environ.get("SCRAPER_KEY", "")
CUTOFF_DAYS = 7
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RemoteRadar/1.0)"}
TIMEOUT = 8  # Short timeout per request

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
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        pass
    try:
        if isinstance(s, (int, float)) and s > 1e10:
            return datetime.fromtimestamp(s/1000, tz=timezone.utc)
    except Exception:
        pass
    return None

def is_recent(date_val, days=CUTOFF_DAYS):
    dt = parse_date(date_val)
    if dt is None:
        return True
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

def make_job(title, company, url, source, date="", location="Remote",
             desc="", salary="", funding="", company_type=""):
    return {
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "url": (url or "").strip(),
        "source": source,
        "date": date,
        "location": (location or "Remote").strip(),
        "desc": (desc or "").strip()[:500],
        "salary": (salary or "").strip(),
        "funding": (funding or "").strip(),
        "company_type": company_type or "",
        "visa": has_visa(desc),
        "hot": is_hot(date),
        "_id": jid(url or title or ""),
    }

# ── Category keywords ─────────────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "tech": ["engineer","developer","software","frontend","backend","fullstack","devops","sre","data engineer","ml","mobile","cloud","security","qa","platform","architect"],
    "product": ["product manager","product lead","product owner","head of product","vp product","chief product","product director","product analyst"],
    "design": ["designer","ux","ui","product designer","graphic designer","visual designer","brand designer","motion designer","design lead","creative director"],
    "marketing": ["marketing manager","marketing lead","growth manager","growth marketing","digital marketing","performance marketing","seo","content marketing","brand manager","cmo","kol manager","influencer marketing","social media manager","content creator","community manager"],
    "community": ["community manager","community lead","community moderator","discord moderator","telegram moderator","moderator","community growth","ambassador","ecosystem growth","community mod"],
    "support": ["customer support","customer success","support specialist","support agent","support manager","help desk","live chat","technical support","cx manager","client success"],
    "sales": ["sales manager","sales lead","account executive","business development","bd manager","sales director","vp sales","head of sales","partnership manager","enterprise sales"],
    "finance": ["finance manager","financial analyst","accountant","controller","cfo","chief financial officer","head of finance","treasury","fp&a"],
    "operations": ["operations manager","ops manager","head of operations","coo","project manager","program manager","business analyst","chief of staff"],
    "hr": ["hr manager","human resources","recruiter","talent acquisition","people manager","head of people","people operations","hr director"],
    "executive": ["ceo","chief executive","president","co-founder","founder","managing director","general manager","country manager","vp","vice president","director","head of","cto","cmo","coo","cfo"],
    "web3": ["web3","crypto","blockchain","defi","nft","dao","dex","protocol","token","wallet","exchange","ethereum","bitcoin","layer2","metaverse","gamefi","on-chain"],
}

EXCLUDE_TITLES = ["intern (unpaid)", "volunteer only", "commission only"]

def is_title_relevant(title, user_keywords, user_category):
    t = title.lower().strip()
    if not t or len(t) < 3:
        return False
    if any(e in t for e in EXCLUDE_TITLES):
        return False
    if user_keywords:
        kws = [k.strip().lower() for k in user_keywords.split(",") if k.strip()]
        if kws and any(k in t for k in kws):
            return True
    if user_category and user_category != "all":
        cat_kws = CATEGORY_KEYWORDS.get(user_category, [])
        return any(k in t for k in cat_kws)
    all_kws = [k for kws in CATEGORY_KEYWORDS.values() for k in kws]
    return any(k in t for k in all_kws)

def matches_location(job_location, user_location, user_remote_only):
    jloc = (job_location or "").lower()
    uloc = (user_location or "").lower()
    if not uloc or uloc in ["worldwide","any","anywhere",""]:
        return True
    if uloc == "remote" or user_remote_only:
        return "remote" in jloc or not jloc or "worldwide" in jloc or "anywhere" in jloc
    location_map = {
        "usa": ["united states","us","usa","america","remote","new york","san francisco"],
        "uk": ["united kingdom","uk","england","britain","london","remote"],
        "india": ["india","bangalore","mumbai","delhi","hyderabad","remote"],
        "nigeria": ["nigeria","lagos","abuja","remote"],
        "europe": ["europe","germany","france","netherlands","spain","italy","remote"],
        "southeast asia": ["indonesia","vietnam","philippines","malaysia","singapore","remote"],
        "middle east": ["uae","dubai","saudi","qatar","remote"],
        "japan": ["japan","tokyo","remote"],
        "china": ["china","beijing","shanghai","remote"],
    }
    for region, cities in location_map.items():
        if region in uloc:
            return any(c in jloc for c in cities)
    return uloc in jloc or "remote" in jloc

def matches_seniority(title, user_level):
    if not user_level or user_level == "all":
        return True
    t = title.lower()
    if user_level == "entry":
        return any(k in t for k in ["junior","entry","associate","assistant","coordinator","grad"])
    if user_level == "mid":
        return not any(k in t for k in ["junior","entry","senior","sr.","lead","principal","director","vp","chief","ceo"])
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
    return True

def score(title, keywords=""):
    t = title.lower()
    s = 0
    if keywords:
        kws = [k.strip().lower() for k in keywords.split(",") if k.strip()]
        s += sum(20 for k in kws if k in t)
    all_kws = [k for kws in CATEGORY_KEYWORDS.values() for k in kws]
    s += sum(5 for k in all_kws if k in t)
    return min(s, 100)

# ── Sources ───────────────────────────────────────────────────────────────────

def scrape_remotive():
    jobs = []
    try:
        r = requests.get("https://remotive.com/api/remote-jobs?limit=100", headers=HEADERS, timeout=TIMEOUT)
        for j in r.json().get("jobs", []):
            if not is_recent(j.get("publication_date","")):
                continue
            jobs.append(make_job(j.get("title",""), j.get("company_name",""), j.get("url",""),
                "Remotive", j.get("publication_date",""), j.get("candidate_required_location","Remote"),
                j.get("description",""), j.get("salary","")))
    except Exception as e:
        print(f"Remotive: {e}")
    print(f"Remotive: {len(jobs)}")
    return jobs

def scrape_wwr():
    jobs = []
    cats = ["remote-marketing-jobs","remote-customer-support-jobs","remote-sales-and-business-development-jobs",
            "remote-product-jobs","remote-design-jobs","remote-finance-legal-jobs","all-other-remote-jobs"]
    for cat in cats:
        try:
            feed = feedparser.parse(f"https://weworkremotely.com/categories/{cat}.rss")
            for e in feed.entries:
                if not is_recent(e.get("published")):
                    continue
                raw = e.get("title","")
                if " at " in raw:
                    title, company = raw.split(" at ")[0].strip(), raw.split(" at ")[-1].strip()
                elif ": " in raw:
                    company, title = raw.split(": ",1)[0].strip(), raw.split(": ",1)[1].strip()
                else:
                    title, company = raw, ""
                jobs.append(make_job(title, company, e.get("link",""), "WeWorkRemotely",
                    e.get("published",""), "Remote", e.get("summary","")))
        except Exception as e:
            print(f"WWR {cat}: {e}")
    print(f"WWR: {len(jobs)}")
    return jobs

def scrape_remoteok():
    jobs = []
    try:
        r = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=TIMEOUT)
        for j in r.json()[1:]:
            if not is_recent(j.get("date","")):
                continue
            jobs.append(make_job(j.get("position",""), j.get("company",""), j.get("url",""),
                "RemoteOK", j.get("date",""), "Remote", j.get("description",""),
                str(j.get("salary","")) if j.get("salary") else ""))
    except Exception as e:
        print(f"RemoteOK: {e}")
    print(f"RemoteOK: {len(jobs)}")
    return jobs

def scrape_jobicy():
    jobs = []
    seen = set()
    try:
        r = requests.get("https://jobicy.com/api/v2/remote-jobs?count=100", headers=HEADERS, timeout=TIMEOUT)
        for j in r.json().get("jobs",[]):
            if not is_recent(j.get("pubDate","")) or j.get("url","") in seen:
                continue
            seen.add(j.get("url",""))
            jobs.append(make_job(j.get("jobTitle",""), j.get("companyName",""), j.get("url",""),
                "Jobicy", j.get("pubDate",""), j.get("jobGeo","Remote"), j.get("jobDescription","")))
    except Exception as e:
        print(f"Jobicy: {e}")
    print(f"Jobicy: {len(jobs)}")
    return jobs

def scrape_himalayas():
    jobs = []
    try:
        r = requests.get("https://himalayas.app/jobs/api?limit=100", headers=HEADERS, timeout=TIMEOUT)
        for j in r.json().get("jobs",[]):
            if not is_recent(j.get("publishedAt","")):
                continue
            salary = ""
            if j.get("salaryMin"):
                salary = f"{j.get('salaryCurrencyCode','')} {j.get('salaryMin',0):,}–{j.get('salaryMax',0):,}"
            funding = j.get("company",{}).get("totalFunding","")
            jobs.append(make_job(j.get("title",""), j.get("company",{}).get("name",""),
                j.get("applicationLink","") or j.get("url",""),
                "Himalayas", j.get("publishedAt",""), j.get("location","Remote"),
                j.get("description",""), salary,
                f"${funding:,}" if isinstance(funding, int) else str(funding),
                "startup" if j.get("company",{}).get("isStartup") else ""))
    except Exception as e:
        print(f"Himalayas: {e}")
    print(f"Himalayas: {len(jobs)}")
    return jobs

def scrape_arbeitnow():
    jobs = []
    try:
        r = requests.get("https://arbeitnow.com/api/job-board-api", headers=HEADERS, timeout=TIMEOUT)
        for j in r.json().get("data",[]):
            if not is_recent(j.get("created_at","")):
                continue
            jobs.append(make_job(j.get("title",""), j.get("company_name",""), j.get("url",""),
                "Arbeitnow", j.get("created_at",""),
                "Remote" if j.get("remote") else j.get("location",""),
                j.get("description","")))
    except Exception as e:
        print(f"Arbeitnow: {e}")
    print(f"Arbeitnow: {len(jobs)}")
    return jobs

def scrape_web3career():
    jobs = []
    seen = set()
    for q in ["community-manager","marketing","business-development","customer-support","growth"]:
        try:
            if SCRAPER_KEY:
                r = requests.get(f"http://api.scraperapi.com?api_key={SCRAPER_KEY}&url=https://web3.career/{q}-jobs", timeout=20)
            else:
                r = requests.get(f"https://web3.career/{q}-jobs", headers=HEADERS, timeout=TIMEOUT)
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup.find_all("h2"):
                title = tag.get_text(strip=True)
                if not title or len(title) < 4:
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
                jobs.append(make_job(title, company, link, "Web3.career", date_str, "Remote"))
        except Exception as e:
            print(f"Web3.career {q}: {e}")
    print(f"Web3.career: {len(jobs)}")
    return jobs

def _fetch_greenhouse(company):
    jobs = []
    try:
        r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true",
                         headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return jobs
        for j in r.json().get("jobs",[]):
            url = j.get("absolute_url","")
            if not is_recent(j.get("updated_at","")) or not url:
                continue
            loc = j.get("location",{}).get("name","Remote")
            jobs.append(make_job(j.get("title",""), company.replace("-"," ").title(),
                url, "Greenhouse", j.get("updated_at",""), loc, j.get("content",""), "","","startup"))
    except Exception:
        pass
    return jobs

def scrape_greenhouse():
    companies = [
        "coinbase","uniswaplabs","chainlink-labs","kraken","gemini","ripple","alchemy",
        "stripe","notion","figma","linear","vercel","supabase","retool",
        "remote","deel","rippling","ramp","canva","miro","airtable","webflow",
        "airbnb","hubspot","intercom","zendesk","dropbox",
    ]
    jobs = []
    seen = set()
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch_greenhouse, c): c for c in companies}
        for fut in as_completed(futures, timeout=60):
            for j in fut.result():
                if j["_id"] not in seen and j["url"]:
                    seen.add(j["_id"])
                    jobs.append(j)
    print(f"Greenhouse: {len(jobs)}")
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
            date_str = datetime.fromtimestamp(created/1000, tz=timezone.utc).isoformat() if created else ""
            if not is_recent(date_str) or not url:
                continue
            loc = j.get("categories",{}).get("location","Remote")
            jobs.append(make_job(j.get("text",""), company.replace("-"," ").title(),
                url, "Lever", date_str, loc, j.get("descriptionPlain",""), "","","startup"))
    except Exception:
        pass
    return jobs

def scrape_lever():
    companies = ["binance","moonpay","fireblocks","chainalysis","nansen","near",
                 "immutable","magic-eden","animoca","cohere","warpcast","gofundme"]
    jobs = []
    seen = set()
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_fetch_lever, c): c for c in companies}
        for fut in as_completed(futures, timeout=60):
            for j in fut.result():
                if j["_id"] not in seen and j["url"]:
                    seen.add(j["_id"])
                    jobs.append(j)
    print(f"Lever: {len(jobs)}")
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
    except Exception:
        pass
    return jobs

def scrape_ashby():
    companies = ["openai","notion","linear","cursor","ramp","deel","vercel",
                 "replit","retool","vanta","mercury","posthog","zapier",
                 "perplexity","brex","rippling","lattice","webflow","beehiiv","phantom"]
    jobs = []
    seen = set()
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch_ashby, c): c for c in companies}
        for fut in as_completed(futures, timeout=60):
            for j in fut.result():
                if j["_id"] not in seen and j["url"]:
                    seen.add(j["_id"])
                    jobs.append(j)
    print(f"Ashby: {len(jobs)}")
    return jobs

def scrape_hn_hiring():
    jobs = []
    try:
        r = requests.get("https://hn.algolia.com/api/v1/search",
                         params={"query":"Ask HN: Who is hiring","tags":"story","hitsPerPage":3},
                         headers=HEADERS, timeout=TIMEOUT)
        hits = r.json().get("hits",[])
        if not hits:
            print("HN Hiring: no thread")
            return jobs
        thread_id = hits[0].get("objectID")
        r2 = requests.get(f"https://hn.algolia.com/api/v1/items/{thread_id}",
                          headers=HEADERS, timeout=TIMEOUT)
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
                "HN: Who is Hiring", created, location, desc, "","","startup"))
    except Exception as e:
        print(f"HN Hiring: {e}")
    print(f"HN Hiring: {len(jobs)}")
    return jobs

def scrape_the_muse():
    jobs = []
    seen = set()
    try:
        r = requests.get("https://www.themuse.com/api/public/jobs",
                         params={"page":0,"page_size":20}, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
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
        print(f"The Muse: {e}")
    print(f"The Muse: {len(jobs)}")
    return jobs

# ── Master fetch (parallel) ───────────────────────────────────────────────────

def get_all_jobs():
    scrapers = [
        scrape_remotive, scrape_wwr, scrape_remoteok, scrape_jobicy,
        scrape_himalayas, scrape_arbeitnow, scrape_web3career,
        scrape_greenhouse, scrape_lever, scrape_ashby,
        scrape_hn_hiring, scrape_the_muse,
    ]

    all_jobs = []
    # Run all scrapers in parallel
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(s): s.__name__ for s in scrapers}
        for fut in as_completed(futures, timeout=500):
            try:
                all_jobs += fut.result()
            except Exception as e:
                print(f"{futures[fut]} failed: {e}")

    # Deduplicate
    seen, unique = set(), []
    for j in all_jobs:
        if j["_id"] not in seen and j["url"]:
            seen.add(j["_id"])
            unique.append(j)

    # Hot jobs first, then by relevance
    unique.sort(key=lambda j: (j.get("hot",False), score(j["title"])), reverse=True)
    print(f"Total unique jobs: {len(unique)}")
    return unique
