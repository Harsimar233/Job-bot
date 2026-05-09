"""
Global Job Engine — covers all categories, all regions, all levels.
No crypto requirement. Works for any job title worldwide.
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
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        pass
    try:
        # Handle millisecond timestamps
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

def make_job(title, company, url, source, date="", location="Remote",
             desc="", salary="", funding="", company_type=""):
    return {
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "url": (url or "").strip(),
        "source": source,
        "date": date,
        "location": (location or "Remote").strip(),
        "desc": (desc or "").strip(),
        "salary": (salary or "").strip(),
        "funding": (funding or "").strip(),
        "company_type": company_type or "",
        "_id": jid(url or title or ""),
    }

# ── Category keywords (all fields) ───────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "tech": [
        "engineer","developer","software","frontend","backend","fullstack","full stack",
        "devops","sre","data engineer","ml engineer","ai engineer","mobile developer",
        "ios developer","android developer","cloud engineer","security engineer",
        "qa engineer","product engineer","platform engineer","infrastructure",
    ],
    "product": [
        "product manager","product lead","product owner","head of product",
        "vp product","chief product","product director","product analyst",
        "product strategist","product operations",
    ],
    "design": [
        "designer","ux","ui","product designer","graphic designer","visual designer",
        "brand designer","motion designer","design lead","head of design",
        "creative director","art director",
    ],
    "marketing": [
        "marketing manager","marketing lead","growth manager","growth marketing",
        "growth hacker","digital marketing","performance marketing","seo","sem",
        "content marketing","email marketing","brand manager","marketing director",
        "vp marketing","cmo","chief marketing","head of marketing",
        "marketing coordinator","marketing specialist","demand generation",
        "product marketing","field marketing","influencer marketing","kol manager",
        "social media manager","social media","content creator","content strategist",
    ],
    "community": [
        "community manager","community lead","community moderator","discord moderator",
        "telegram moderator","moderator","community growth","ambassador",
        "community operations","community advocate","ecosystem growth",
        "ambassador program","partnership manager","community building",
    ],
    "support": [
        "customer support","customer success","support specialist","support agent",
        "support manager","help desk","live chat","technical support",
        "customer experience","cx manager","client success","account manager",
    ],
    "sales": [
        "sales manager","sales lead","account executive","business development",
        "bd manager","sales director","vp sales","head of sales","revenue manager",
        "partnership manager","channel sales","enterprise sales","smb sales",
        "sales representative","sales coordinator","chief revenue officer","cro",
    ],
    "finance": [
        "finance manager","financial analyst","accountant","controller","cfo",
        "chief financial officer","head of finance","treasury","fp&a",
        "finance director","financial controller","bookkeeper","payroll",
        "investment analyst","venture capital","private equity",
    ],
    "operations": [
        "operations manager","ops manager","head of operations","coo",
        "chief operating officer","project manager","program manager",
        "operations coordinator","business analyst","process manager",
        "strategy manager","chief of staff","executive assistant",
    ],
    "hr": [
        "hr manager","human resources","recruiter","talent acquisition",
        "people manager","head of people","people operations","hr director",
        "vp people","chro","chief people officer","hr business partner",
        "learning and development","compensation","benefits manager",
    ],
    "executive": [
        "ceo","chief executive","president","co-founder","founder",
        "managing director","general manager","country manager","regional director",
        "vp","vice president","director","head of","chief","c-suite",
        "cto","cmo","coo","cfo","cro","cpo","ciso",
    ],
    "web3": [
        "web3","crypto","blockchain","defi","nft","dao","dex","protocol",
        "token","wallet","exchange","smart contract","solidity","ethereum",
        "bitcoin","layer2","l2","metaverse","gamefi","yield","staking",
    ],
}

EXCLUDE_TITLES = [
    "intern (unpaid)","volunteer only","commission only",
]

def is_title_relevant(title, user_keywords, user_category):
    """Check if job title matches user preferences."""
    t = title.lower().strip()
    if not t or len(t) < 3:
        return False
    if any(e in t for e in EXCLUDE_TITLES):
        return False

    # If user set specific keywords, match those
    if user_keywords:
        kws = [k.strip().lower() for k in user_keywords.split(",") if k.strip()]
        if kws and any(k in t for k in kws):
            return True

    # Match by category
    if user_category and user_category != "all":
        cat_kws = CATEGORY_KEYWORDS.get(user_category, [])
        return any(k in t for k in cat_kws)

    # "all" category — match any known role keyword
    all_kws = [k for kws in CATEGORY_KEYWORDS.values() for k in kws]
    return any(k in t for k in all_kws)

def matches_location(job_location, user_location, user_remote_only):
    """Check if job location matches user preference."""
    jloc = (job_location or "").lower()
    uloc = (user_location or "").lower()

    if not uloc or uloc in ["worldwide", "any", "anywhere", ""]:
        return True

    if uloc == "remote" or user_remote_only:
        return "remote" in jloc or not jloc

    # Location-based matching
    location_map = {
        "usa": ["united states", "us", "usa", "america", "remote"],
        "uk": ["united kingdom", "uk", "england", "britain", "london", "remote"],
        "india": ["india", "bangalore", "mumbai", "delhi", "remote"],
        "nigeria": ["nigeria", "lagos", "abuja", "remote"],
        "europe": ["europe", "germany", "france", "netherlands", "spain", "remote"],
        "southeast asia": ["indonesia", "vietnam", "philippines", "malaysia", "singapore", "remote"],
        "middle east": ["uae", "dubai", "saudi", "qatar", "remote"],
        "japan": ["japan", "tokyo", "remote"],
        "china": ["china", "beijing", "shanghai", "remote"],
    }

    for region, cities in location_map.items():
        if region in uloc:
            return any(c in jloc for c in cities)

    return uloc in jloc or "remote" in jloc

def matches_seniority(title, user_level):
    """Check if job matches user's seniority preference."""
    if not user_level or user_level == "all":
        return True

    t = title.lower()
    level_map = {
        "entry": ["junior","entry","associate","assistant","coordinator","specialist i"],
        "mid": ["mid","intermediate","specialist","analyst",""],
        "senior": ["senior","sr.","lead","principal","staff"],
        "manager": ["manager","lead","head of","supervisor"],
        "director": ["director","vp","vice president","head of"],
        "executive": ["ceo","cto","cmo","coo","cfo","cro","chief","president","founder"],
    }

    allowed = level_map.get(user_level, [])
    if user_level == "mid":
        # Mid level = not junior, not senior, not executive
        return (not any(k in t for k in ["junior","entry","associate","senior","sr.","lead","director","vp","chief","ceo"]))
    return any(k in t for k in allowed) if allowed else True

def matches_user(job, user):
    """Full match check for a user's preferences."""
    keywords = user.get("keywords", "")
    category = user.get("category", "all")
    location = user.get("location", "Remote")
    remote_only = user.get("remote_only", True)
    seniority = user.get("seniority", "all")

    if not is_title_relevant(job["title"], keywords, category):
        return False
    if not matches_location(job["location"], location, remote_only):
        return False
    if not matches_seniority(job["title"], seniority):
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


# ── Source 1: Remotive (all categories, global) ───────────────────────────────

def scrape_remotive():
    jobs = []
    try:
        r = requests.get("https://remotive.com/api/remote-jobs?limit=100", headers=HEADERS, timeout=15)
        for j in r.json().get("jobs", []):
            pub = j.get("publication_date", "")
            if not is_recent(pub):
                continue
            salary = j.get("salary", "")
            jobs.append(make_job(
                j.get("title",""), j.get("company_name",""),
                j.get("url",""), "Remotive",
                pub, j.get("candidate_required_location","Remote"),
                j.get("description",""), salary
            ))
    except Exception as e:
        print(f"Remotive: {e}")
    print(f"Remotive: {len(jobs)}")
    return jobs


# ── Source 2: WeWorkRemotely (all categories) ─────────────────────────────────

def scrape_wwr():
    jobs = []
    cats = [
        "remote-full-stack-programming-jobs",
        "remote-front-end-programming-jobs",
        "remote-back-end-programming-jobs",
        "remote-marketing-jobs",
        "remote-customer-support-jobs",
        "remote-sales-and-business-development-jobs",
        "remote-product-jobs",
        "remote-design-jobs",
        "remote-devops-sysadmin-jobs",
        "remote-finance-legal-jobs",
        "remote-human-resources-jobs",
        "all-other-remote-jobs",
    ]
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


# ── Source 3: RemoteOK (all categories) ──────────────────────────────────────

def scrape_remoteok():
    jobs = []
    try:
        r = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=10)
        for j in r.json()[1:]:
            if not is_recent(j.get("date","")):
                continue
            tags = " ".join(j.get("tags",[]))
            salary = j.get("salary","")
            jobs.append(make_job(
                j.get("position",""), j.get("company",""),
                j.get("url",""), "RemoteOK",
                j.get("date",""), "Remote",
                j.get("description",""), str(salary) if salary else ""
            ))
    except Exception as e:
        print(f"RemoteOK: {e}")
    print(f"RemoteOK: {len(jobs)}")
    return jobs


# ── Source 4: Jobicy (all categories) ────────────────────────────────────────

def scrape_jobicy():
    jobs = []
    seen = set()
    try:
        r = requests.get("https://jobicy.com/api/v2/remote-jobs?count=100",
                         headers=HEADERS, timeout=10)
        for j in r.json().get("jobs",[]):
            if not is_recent(j.get("pubDate","")):
                continue
            url = j.get("url","")
            if url in seen:
                continue
            seen.add(url)
            jobs.append(make_job(
                j.get("jobTitle",""), j.get("companyName",""),
                url, "Jobicy",
                j.get("pubDate",""), j.get("jobGeo","Remote"),
                j.get("jobDescription","")
            ))
    except Exception as e:
        print(f"Jobicy: {e}")
    print(f"Jobicy: {len(jobs)}")
    return jobs


# ── Source 5: Himalayas (global, all categories) ──────────────────────────────

def scrape_himalayas():
    jobs = []
    try:
        r = requests.get("https://himalayas.app/jobs/api?limit=100",
                         headers=HEADERS, timeout=15)
        for j in r.json().get("jobs", []):
            pub = j.get("publishedAt","")
            if not is_recent(pub):
                continue
            salary = ""
            if j.get("salaryCurrencyCode") and j.get("salaryMin"):
                salary = f"{j.get('salaryCurrencyCode')} {j.get('salaryMin',0):,}–{j.get('salaryMax',0):,}"
            # Funding info
            funding = j.get("company",{}).get("totalFunding","")
            company_type = "startup" if j.get("company",{}).get("isStartup") else ""
            jobs.append(make_job(
                j.get("title",""),
                j.get("company",{}).get("name",""),
                j.get("applicationLink","") or j.get("url",""),
                "Himalayas",
                pub,
                j.get("location","Remote"),
                j.get("description",""),
                salary,
                f"${funding:,}" if isinstance(funding, int) else str(funding),
                company_type
            ))
    except Exception as e:
        print(f"Himalayas: {e}")
    print(f"Himalayas: {len(jobs)}")
    return jobs


# ── Source 6: WorkingNomads RSS (global remote) ───────────────────────────────

def scrape_workingnomads():
    jobs = []
    categories = ["it","marketing","sales","design","management","finance","all"]
    seen = set()
    for cat in categories:
        try:
            feed = feedparser.parse(f"https://www.workingnomads.com/feed?category={cat}")
            for e in feed.entries:
                if not is_recent(e.get("published","")):
                    continue
                link = e.get("link","")
                if link in seen:
                    continue
                seen.add(link)
                title, company = e.get("title",""), ""
                if " - " in title:
                    parts = title.split(" - ")
                    title, company = parts[0].strip(), parts[-1].strip()
                jobs.append(make_job(title, company, link, "WorkingNomads",
                                     e.get("published",""), "Remote", e.get("summary","")))
        except Exception as e:
            print(f"WorkingNomads {cat}: {e}")
    print(f"WorkingNomads: {len(jobs)}")
    return jobs


# ── Source 7: Web3.career (web3 specific) ────────────────────────────────────

def scrape_web3career():
    jobs = []
    seen = set()
    for q in ["community-manager","marketing","business-development","product-manager",
               "customer-support","social-media","operations","growth"]:
        try:
            r = scrape_url(f"https://web3.career/{q}-jobs")
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


# ── Source 8: Greenhouse (startup/funded companies) ───────────────────────────

GREENHOUSE_COMPANIES = [
    # Big crypto/web3
    "coinbase","uniswaplabs","chainlink-labs","polygon-labs","arbitrum",
    "optimism-pbc","aave","opensea","consensys","ledger","kraken","gemini",
    "ripple","blockchain-com","bitgo","anchorage","alchemy","metamask",
    # Tech startups
    "stripe","notion","figma","linear","vercel","supabase","planetscale",
    "retool","clerk","loom","descript","runway","harvey","glean",
    # Global companies
    "remote","deel","oyster","rippling","gusto","lattice","ramp",
]

def scrape_greenhouse():
    jobs = []
    seen = set()
    for company in GREENHOUSE_COMPANIES:
        try:
            r = requests.get(
                f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true",
                headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            for j in r.json().get("jobs",[]):
                url = j.get("absolute_url","")
                updated = j.get("updated_at","")
                if not is_recent(updated) or url in seen:
                    continue
                seen.add(url)
                loc = j.get("location",{}).get("name","Remote")
                jobs.append(make_job(
                    j.get("title",""),
                    company.replace("-"," ").title(),
                    url, "Greenhouse", updated, loc,
                    j.get("content",""), "", "", "startup"
                ))
        except Exception as e:
            print(f"Greenhouse {company}: {e}")
    print(f"Greenhouse: {len(jobs)}")
    return jobs


# ── Source 9: Lever (startups worldwide) ─────────────────────────────────────

LEVER_COMPANIES = [
    "binance","moonpay","fireblocks","chainalysis","nansen","dune",
    "the-graph","near","immutable","magic-eden","animoca",
    "scale-ai","hugging-face","anthropic","cohere","mistral",
    "warpcast","farcaster","zora",
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
                url = j.get("hostedUrl","")
                created = j.get("createdAt",0)
                date_str = datetime.fromtimestamp(created/1000, tz=timezone.utc).isoformat() if created else ""
                if not is_recent(date_str) or url in seen:
                    continue
                seen.add(url)
                loc = j.get("categories",{}).get("location","Remote")
                jobs.append(make_job(
                    j.get("text",""),
                    company.replace("-"," ").title(),
                    url, "Lever", date_str, loc,
                    j.get("descriptionPlain",""), "", "", "startup"
                ))
        except Exception as e:
            print(f"Lever {company}: {e}")
    print(f"Lever: {len(jobs)}")
    return jobs


# ── Master fetch ──────────────────────────────────────────────────────────────

def get_all_jobs():
    all_jobs = []
    for fn in [scrape_remotive, scrape_wwr, scrape_remoteok, scrape_jobicy,
               scrape_himalayas, scrape_workingnomads, scrape_web3career,
               scrape_greenhouse, scrape_lever]:
        try:
            all_jobs += fn()
        except Exception as e:
            print(f"{fn.__name__} crashed: {e}")

    # Deduplicate
    seen, unique = set(), []
    for j in all_jobs:
        if j["_id"] not in seen and j["url"]:
            seen.add(j["_id"])
            unique.append(j)

    print(f"Total unique jobs: {len(unique)}")
    return unique
