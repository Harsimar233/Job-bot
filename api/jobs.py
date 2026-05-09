"""
Global Job Engine — 15+ sources covering worldwide.
India, Nigeria, Japan, UK, USA, Europe, SE Asia, Middle East & more.
"""
import re, requests, feedparser, hashlib
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime

SCRAPER_KEY  = __import__("os").environ.get("SCRAPER_KEY", "")
ADZUNA_ID    = __import__("os").environ.get("ADZUNA_ID", "")
ADZUNA_KEY   = __import__("os").environ.get("ADZUNA_KEY", "")
CUTOFF_DAYS  = 7
HEADERS      = {"User-Agent": "Mozilla/5.0 (compatible; RemoteRadar/1.0)"}

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

# ── Category keywords ─────────────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "tech": ["engineer","developer","software","frontend","backend","fullstack","devops",
             "sre","data engineer","ml engineer","mobile","ios","android","cloud","security",
             "qa","platform","infrastructure"],
    "product": ["product manager","product lead","product owner","head of product",
                "vp product","chief product","product director","product analyst"],
    "design": ["designer","ux","ui","product designer","graphic designer","visual designer",
               "brand designer","motion designer","design lead","creative director"],
    "marketing": ["marketing manager","marketing lead","growth manager","growth marketing",
                  "digital marketing","performance marketing","seo","sem","content marketing",
                  "email marketing","brand manager","marketing director","vp marketing","cmo",
                  "kol manager","influencer marketing","social media manager","social media",
                  "content creator","content strategist"],
    "community": ["community manager","community lead","community moderator","discord moderator",
                  "telegram moderator","moderator","community growth","ambassador",
                  "community operations","community advocate","ecosystem growth",
                  "ambassador program","community building"],
    "support": ["customer support","customer success","support specialist","support agent",
                "support manager","help desk","live chat","technical support",
                "customer experience","cx manager","client success","account manager"],
    "sales": ["sales manager","sales lead","account executive","business development",
              "bd manager","sales director","vp sales","head of sales","revenue manager",
              "partnership manager","enterprise sales","sales representative"],
    "finance": ["finance manager","financial analyst","accountant","controller","cfo",
                "chief financial officer","head of finance","treasury","fp&a","bookkeeper"],
    "operations": ["operations manager","ops manager","head of operations","coo",
                   "project manager","program manager","business analyst","chief of staff"],
    "hr": ["hr manager","human resources","recruiter","talent acquisition","people manager",
           "head of people","people operations","hr director","chro"],
    "executive": ["ceo","chief executive","president","co-founder","founder",
                  "managing director","general manager","country manager","regional director",
                  "vp","vice president","director","head of","cto","cmo","coo","cfo"],
    "web3": ["web3","crypto","blockchain","defi","nft","dao","dex","protocol","token",
             "wallet","exchange","smart contract","ethereum","bitcoin","layer2","metaverse"],
}

EXCLUDE_TITLES = ["intern (unpaid)","volunteer only","commission only"]

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
    if not uloc or uloc in ["worldwide", "any", "anywhere", ""]:
        return True
    if uloc == "remote" or user_remote_only:
        return "remote" in jloc or not jloc
    location_map = {
        "usa": ["united states","us","usa","america","remote"],
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
    level_map = {
        "entry": ["junior","entry","associate","assistant","coordinator"],
        "senior": ["senior","sr.","lead","principal","staff"],
        "manager": ["manager","lead","head of","supervisor"],
        "director": ["director","vp","vice president"],
        "executive": ["ceo","cto","cmo","coo","cfo","chief","president","founder"],
    }
    allowed = level_map.get(user_level, [])
    if user_level == "mid":
        return not any(k in t for k in ["junior","entry","senior","sr.","director","vp","chief","ceo"])
    return any(k in t for k in allowed) if allowed else True

def matches_user(job, user):
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


# ── SOURCE 1: Remotive (global remote) ───────────────────────────────────────

def scrape_remotive():
    jobs = []
    try:
        r = requests.get("https://remotive.com/api/remote-jobs?limit=100", headers=HEADERS, timeout=15)
        for j in r.json().get("jobs", []):
            if not is_recent(j.get("publication_date","")):
                continue
            jobs.append(make_job(
                j.get("title",""), j.get("company_name",""),
                j.get("url",""), "Remotive",
                j.get("publication_date",""),
                j.get("candidate_required_location","Remote"),
                j.get("description",""), j.get("salary","")
            ))
    except Exception as e:
        print(f"Remotive: {e}")
    print(f"Remotive: {len(jobs)}")
    return jobs


# ── SOURCE 2: WeWorkRemotely (all categories) ─────────────────────────────────

def scrape_wwr():
    jobs = []
    cats = [
        "remote-full-stack-programming-jobs","remote-front-end-programming-jobs",
        "remote-back-end-programming-jobs","remote-marketing-jobs",
        "remote-customer-support-jobs","remote-sales-and-business-development-jobs",
        "remote-product-jobs","remote-design-jobs","remote-devops-sysadmin-jobs",
        "remote-finance-legal-jobs","remote-human-resources-jobs","all-other-remote-jobs",
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


# ── SOURCE 3: RemoteOK ────────────────────────────────────────────────────────

def scrape_remoteok():
    jobs = []
    try:
        r = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=10)
        for j in r.json()[1:]:
            if not is_recent(j.get("date","")):
                continue
            jobs.append(make_job(
                j.get("position",""), j.get("company",""),
                j.get("url",""), "RemoteOK", j.get("date",""), "Remote",
                j.get("description",""), str(j.get("salary","")) if j.get("salary") else ""
            ))
    except Exception as e:
        print(f"RemoteOK: {e}")
    print(f"RemoteOK: {len(jobs)}")
    return jobs


# ── SOURCE 4: Jobicy ──────────────────────────────────────────────────────────

def scrape_jobicy():
    jobs = []
    seen = set()
    try:
        r = requests.get("https://jobicy.com/api/v2/remote-jobs?count=100",
                         headers=HEADERS, timeout=10)
        for j in r.json().get("jobs",[]):
            if not is_recent(j.get("pubDate","")) or j.get("url","") in seen:
                continue
            seen.add(j.get("url",""))
            jobs.append(make_job(
                j.get("jobTitle",""), j.get("companyName",""),
                j.get("url",""), "Jobicy",
                j.get("pubDate",""), j.get("jobGeo","Remote"),
                j.get("jobDescription","")
            ))
    except Exception as e:
        print(f"Jobicy: {e}")
    print(f"Jobicy: {len(jobs)}")
    return jobs


# ── SOURCE 5: Himalayas ───────────────────────────────────────────────────────

def scrape_himalayas():
    jobs = []
    try:
        r = requests.get("https://himalayas.app/jobs/api?limit=100",
                         headers=HEADERS, timeout=15)
        for j in r.json().get("jobs", []):
            if not is_recent(j.get("publishedAt","")):
                continue
            salary = ""
            if j.get("salaryMin"):
                salary = f"{j.get('salaryCurrencyCode','')} {j.get('salaryMin',0):,}–{j.get('salaryMax',0):,}"
            funding = j.get("company",{}).get("totalFunding","")
            company_type = "startup" if j.get("company",{}).get("isStartup") else ""
            jobs.append(make_job(
                j.get("title",""), j.get("company",{}).get("name",""),
                j.get("applicationLink","") or j.get("url",""),
                "Himalayas", j.get("publishedAt",""),
                j.get("location","Remote"), j.get("description",""),
                salary, f"${funding:,}" if isinstance(funding, int) else str(funding),
                company_type
            ))
    except Exception as e:
        print(f"Himalayas: {e}")
    print(f"Himalayas: {len(jobs)}")
    return jobs


# ── SOURCE 6: Arbeitnow (Europe + Remote, no key needed) ─────────────────────

def scrape_arbeitnow():
    jobs = []
    try:
        r = requests.get("https://arbeitnow.com/api/job-board-api",
                         headers=HEADERS, timeout=15)
        for j in r.json().get("data", []):
            if not is_recent(j.get("created_at","")):
                continue
            jobs.append(make_job(
                j.get("title",""), j.get("company_name",""),
                j.get("url",""), "Arbeitnow",
                j.get("created_at",""),
                "Remote" if j.get("remote") else j.get("location",""),
                j.get("description","")
            ))
    except Exception as e:
        print(f"Arbeitnow: {e}")
    print(f"Arbeitnow: {len(jobs)}")
    return jobs


# ── SOURCE 7: Remote.co (RSS) ─────────────────────────────────────────────────

def scrape_remoteco():
    jobs = []
    try:
        feed = feedparser.parse("https://remote.co/remote-jobs/feed/")
        for e in feed.entries:
            if not is_recent(e.get("published","")):
                continue
            title = e.get("title","")
            company = ""
            if " at " in title:
                title, company = title.split(" at ",1)[0].strip(), title.split(" at ",1)[1].strip()
            jobs.append(make_job(title, company, e.get("link",""), "Remote.co",
                                 e.get("published",""), "Remote", e.get("summary","")))
    except Exception as e:
        print(f"Remote.co: {e}")
    print(f"Remote.co: {len(jobs)}")
    return jobs


# ── SOURCE 8: WorkingNomads ───────────────────────────────────────────────────

def scrape_workingnomads():
    jobs = []
    seen = set()
    for cat in ["it","marketing","sales","design","management","all"]:
        try:
            feed = feedparser.parse(f"https://www.workingnomads.com/feed?category={cat}")
            for e in feed.entries:
                if not is_recent(e.get("published","")) or e.get("link","") in seen:
                    continue
                seen.add(e.get("link",""))
                title, company = e.get("title",""), ""
                if " - " in title:
                    parts = title.split(" - ")
                    title, company = parts[0].strip(), parts[-1].strip()
                jobs.append(make_job(title, company, e.get("link",""), "WorkingNomads",
                                     e.get("published",""), "Remote", e.get("summary","")))
        except Exception as e:
            print(f"WorkingNomads {cat}: {e}")
    print(f"WorkingNomads: {len(jobs)}")
    return jobs


# ── SOURCE 9: Adzuna API (19 countries — GLOBAL) ─────────────────────────────

ADZUNA_COUNTRIES = {
    "gb": "UK", "us": "USA", "in": "India", "au": "Australia",
    "de": "Germany", "fr": "France", "ca": "Canada", "sg": "Singapore",
    "za": "South Africa", "nl": "Netherlands", "br": "Brazil",
    "it": "Italy", "es": "Spain", "pl": "Poland", "at": "Austria",
    "be": "Belgium", "mx": "Mexico", "nz": "New Zealand", "ch": "Switzerland",
}

ADZUNA_QUERIES = [
    "community manager", "social media manager", "marketing manager",
    "customer support", "business development", "product manager",
    "growth manager", "ambassador", "operations manager", "hr manager",
    "software engineer", "data analyst", "designer", "sales manager",
]

def scrape_adzuna():
    if not ADZUNA_ID or not ADZUNA_KEY:
        print("Adzuna: no credentials")
        return []
    jobs = []
    seen = set()
    # Search top countries with most relevant queries
    priority_countries = ["gb", "us"]
    for country in priority_countries:
        country_name = ADZUNA_COUNTRIES.get(country, country.upper())
        for query in ADZUNA_QUERIES[:5]:  # Limit queries per country to save API calls
            try:
                r = requests.get(
                    f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
                    params={
                        "app_id": ADZUNA_ID,
                        "app_key": ADZUNA_KEY,
                        "results_per_page": 20,
                        "what": query,
                        "sort_by": "date",
                        "content-type": "application/json",
                    },
                    headers=HEADERS, timeout=15
                )
                if r.status_code != 200:
                    continue
                for j in r.json().get("results", []):
                    url = j.get("redirect_url","")
                    if not url or url in seen:
                        continue
                    if not is_recent(j.get("created","")):
                        continue
                    seen.add(url)
                    salary = ""
                    if j.get("salary_min"):
                        salary = f"£{j['salary_min']:,.0f}–£{j['salary_max']:,.0f}" if country == "gb" else f"${j['salary_min']:,.0f}–${j['salary_max']:,.0f}"
                    location = j.get("location",{}).get("display_name", country_name)
                    jobs.append(make_job(
                        j.get("title",""),
                        j.get("company",{}).get("display_name",""),
                        url, f"Adzuna ({country_name})",
                        j.get("created",""), location,
                        j.get("description",""), salary
                    ))
            except Exception as e:
                print(f"Adzuna {country} {query}: {e}")
    print(f"Adzuna: {len(jobs)}")
    return jobs


# ── SOURCE 10: Web3.career ────────────────────────────────────────────────────

def scrape_web3career():
    jobs = []
    seen = set()
    for q in ["community-manager","marketing","business-development","customer-support",
               "social-media","operations","growth","product-manager"]:
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


# ── SOURCE 11: Greenhouse (funded companies) ──────────────────────────────────

GREENHOUSE_COMPANIES = [
    "coinbase","uniswaplabs","chainlink-labs","polygon-labs","arbitrum",
    "optimism-pbc","aave","opensea","consensys","ledger","kraken","gemini",
    "ripple","blockchain-com","bitgo","anchorage","alchemy","metamask",
    "stripe","notion","figma","linear","vercel","supabase","retool",
    "remote","deel","oyster","rippling","gusto","lattice","ramp",
    "airbnb","dropbox","hubspot","intercom","zendesk","atlassian",
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
                if not is_recent(j.get("updated_at","")) or url in seen:
                    continue
                seen.add(url)
                loc = j.get("location",{}).get("name","Remote")
                jobs.append(make_job(
                    j.get("title",""), company.replace("-"," ").title(),
                    url, "Greenhouse", j.get("updated_at",""), loc,
                    j.get("content",""), "", "", "startup"
                ))
        except Exception as e:
            print(f"Greenhouse {company}: {e}")
    print(f"Greenhouse: {len(jobs)}")
    return jobs


# ── SOURCE 12: Lever (startups) ───────────────────────────────────────────────

LEVER_COMPANIES = [
    "binance","moonpay","fireblocks","chainalysis","nansen","dune",
    "the-graph","near","immutable","magic-eden","animoca",
    "scale-ai","hugging-face","cohere","warpcast",
    "gofundme","canva","miro","airtable","webflow",
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
                    j.get("text",""), company.replace("-"," ").title(),
                    url, "Lever", date_str, loc,
                    j.get("descriptionPlain",""), "", "", "startup"
                ))
        except Exception as e:
            print(f"Lever {company}: {e}")
    print(f"Lever: {len(jobs)}")
    return jobs


# ── SOURCE 13: Jobberman (Nigeria) ────────────────────────────────────────────

def scrape_jobberman():
    jobs = []
    try:
        r = scrape_url("https://www.jobberman.com/jobs?q=&location=nigeria")
        soup = BeautifulSoup(r.text, "html.parser")
        for card in soup.select("article.job-card, div.job-card, li.job-item")[:30]:
            title_el = card.select_one("h2, h3, .job-title, [class*='title']")
            company_el = card.select_one(".company-name, [class*='company']")
            link_el = card.select_one("a[href]")
            if not title_el or not link_el:
                continue
            href = link_el.get("href","")
            link = ("https://www.jobberman.com" + href) if href.startswith("/") else href
            jobs.append(make_job(
                title_el.get_text(strip=True),
                company_el.get_text(strip=True) if company_el else "",
                link, "Jobberman (Nigeria)", "", "Nigeria"
            ))
    except Exception as e:
        print(f"Jobberman: {e}")
    print(f"Jobberman: {len(jobs)}")
    return jobs


# ── SOURCE 14: GaijinPot (Japan) ─────────────────────────────────────────────

def scrape_gaijinpot():
    jobs = []
    try:
        feed = feedparser.parse("https://jobs.gaijinpot.com/index/index/rss")
        for e in feed.entries:
            if not is_recent(e.get("published","")):
                continue
            jobs.append(make_job(
                e.get("title",""), "",
                e.get("link",""), "GaijinPot (Japan)",
                e.get("published",""), "Japan", e.get("summary","")
            ))
    except Exception as e:
        print(f"GaijinPot: {e}")
    print(f"GaijinPot: {len(jobs)}")
    return jobs


# ── SOURCE 15: Indeed RSS (India + Global) ───────────────────────────────────

def scrape_indeed():
    jobs = []
    seen = set()
    searches = [
        ("in", "community manager"),
        ("in", "marketing manager"),
        ("in", "customer support"),
        ("in", "social media manager"),
        ("www", "remote community manager"),
        ("www", "remote marketing manager"),
        ("www", "remote web3 jobs"),
    ]
    for domain, query in searches:
        try:
            url = f"https://{domain}.indeed.com/rss?q={query.replace(' ','+')}&sort=date"
            feed = feedparser.parse(url)
            for e in feed.entries:
                if not is_recent(e.get("published","")) or e.get("link","") in seen:
                    continue
                seen.add(e.get("link",""))
                title = e.get("title","")
                location = "India" if domain == "in" else "Remote"
                jobs.append(make_job(title, "", e.get("link",""), "Indeed",
                                     e.get("published",""), location, e.get("summary","")))
        except Exception as e:
            print(f"Indeed {domain}: {e}")
    print(f"Indeed: {len(jobs)}")
    return jobs


# ── Master fetch ──────────────────────────────────────────────────────────────

def get_all_jobs():
    all_jobs = []
    sources = [
        scrape_remotive, scrape_wwr, scrape_remoteok, scrape_jobicy,
        scrape_himalayas, scrape_arbeitnow, scrape_remoteco,
        scrape_workingnomads, scrape_adzuna, scrape_web3career,
        scrape_greenhouse, scrape_lever, scrape_jobberman,
        scrape_gaijinpot, scrape_indeed,
    ]
    for fn in sources:
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
