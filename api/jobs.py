"""
Remote Radar — Job Sources
Scrapes 15+ sources globally, no Adzuna needed.
"""
import os, re, requests, feedparser, hashlib
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

SCRAPER_KEY = os.environ.get("SCRAPER_KEY", "")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def get(url, timeout=12, scraper=False):
    try:
        if scraper and SCRAPER_KEY:
            r = requests.get(
                "http://api.scraperapi.com",
                params={"api_key": SCRAPER_KEY, "url": url},
                timeout=timeout, headers=HEADERS
            )
        else:
            r = requests.get(url, timeout=timeout, headers=HEADERS)
        return r
    except Exception:
        return None

def job_id(title, company, url=""):
    raw = f"{title}|{company}|{url}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]

def is_recent(date_str, days=10):
    if not date_str:
        return True  # include if no date
    try:
        for fmt in ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z",
                    "%a, %d %b %Y %H:%M:%S GMT"]:
            try:
                dt = datetime.strptime(date_str[:25], fmt[:len(date_str[:25])])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return (datetime.now(timezone.utc) - dt).days <= days
            except Exception:
                continue
    except Exception:
        pass
    return True

def is_hot(date_str):
    """Posted in last 24 hours"""
    if not date_str:
        return False
    try:
        for fmt in ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"]:
            try:
                dt = datetime.strptime(date_str[:19], fmt[:19])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return (datetime.now(timezone.utc) - dt).total_seconds() < 86400
            except Exception:
                continue
    except Exception:
        pass
    return False

def fmt_date(date_str):
    if not date_str:
        return ""
    try:
        for fmt in ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"]:
            try:
                dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
                return dt.strftime("%d %b %Y")
            except Exception:
                continue
    except Exception:
        pass
    return date_str[:10]

def detect_visa(text):
    text = text.lower()
    return any(x in text for x in ["visa sponsor", "work authorization", "right to work", "sponsorship available"])

def detect_salary(text):
    """Extract salary info from text"""
    patterns = [
        r'\$[\d,]+k?\s*[-–]\s*\$[\d,]+k?',
        r'£[\d,]+k?\s*[-–]\s*£[\d,]+k?',
        r'€[\d,]+k?\s*[-–]\s*€[\d,]+k?',
        r'[\d,]+\s*[-–]\s*[\d,]+\s*(?:USD|EUR|GBP|INR)',
        r'\$[\d,]+k?\+?\s*(?:per year|\/yr|\/year|pa|annually)?',
        r'up to \$[\d,]+',
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(0).strip()
    return ""

KEYWORDS_ALL = [
    "community", "moderator", "ambassador", "discord", "telegram", "social media",
    "marketing", "growth", "content", "brand", "kol", "influencer", "partnership",
    "customer support", "customer success", "support specialist", "help desk",
    "manager", "director", "lead", "head of", "vp ", "chief", "cmo", "ceo", "cto",
    "engineer", "developer", "frontend", "backend", "fullstack", "devops",
    "product", "design", "data", "analyst", "finance", "operations", "hr",
    "sales", "business development", "account", "web3", "blockchain", "defi", "nft",
    "crypto", "solidity", "dao", "remote", "coordinator", "specialist", "associate"
]

EXCLUDE_ALWAYS = [
    "mandarin only", "native japanese", "native korean", "chinese only",
    "требуется", "только на русском"  # Russian-only roles
]

def is_relevant(title):
    title_l = title.lower()
    if any(x in title_l for x in EXCLUDE_ALWAYS):
        return False
    return len(title) > 4  # Accept almost everything, let user filter

def make_job(title, company, url, source, date="", location="Remote",
             salary="", funding="", company_type="", visa=False, description=""):
    return {
        "id": job_id(title, company, url),
        "title": title.strip(),
        "company": (company or "").strip(),
        "url": url,
        "source": source,
        "date": date,
        "location": location,
        "salary": salary,
        "funding": funding,
        "company_type": company_type,
        "visa": visa,
        "hot": is_hot(date),
        "description": description[:300] if description else "",
    }


# ── Sources ───────────────────────────────────────────────────────────────────

def scrape_remotive():
    jobs = []
    try:
        r = get("https://remotive.com/api/remote-jobs?limit=100")
        if not r: return jobs
        for j in r.json().get("jobs", []):
            if not is_recent(j.get("publication_date", "")): continue
            desc = j.get("description", "")
            sal = detect_salary(desc) or j.get("salary", "")
            jobs.append(make_job(
                j.get("title", ""), j.get("company_name", ""),
                j.get("url", ""), "Remotive",
                j.get("publication_date", ""), j.get("candidate_required_location", "Remote"),
                salary=sal
            ))
    except Exception as e:
        print(f"Remotive error: {e}")
    print(f"Remotive: {len(jobs)}")
    return jobs


def scrape_wwr():
    jobs = []
    CATS = ["remote-jobs", "marketing-jobs", "customer-service-jobs",
            "management-business-jobs", "all-other-jobs"]
    for cat in CATS:
        try:
            feed = feedparser.parse(f"https://weworkremotely.com/{cat}/feed")
            for e in feed.entries:
                if not is_recent(e.get("published", "")): continue
                title = re.sub(r'\[.*?\]', '', e.get("title", "")).strip()
                company = e.get("author", "")
                jobs.append(make_job(title, company, e.get("link", ""), "WeWorkRemotely",
                                     e.get("published", "")))
        except Exception as e:
            print(f"WWR {cat}: {e}")
    print(f"WWR: {len(jobs)}")
    return jobs


def scrape_remoteok():
    jobs = []
    try:
        r = get("https://remoteok.com/api")
        if not r: return jobs
        data = r.json()
        for j in data[1:]:  # skip first item (metadata)
            if not isinstance(j, dict): continue
            if not is_recent(j.get("date", "")): continue
            desc = j.get("description", "")
            sal = detect_salary(desc) or (f"${j['salary_min']}–${j['salary_max']}" if j.get("salary_min") else "")
            jobs.append(make_job(
                j.get("position", ""), j.get("company", ""),
                j.get("url", "https://remoteok.com"), "RemoteOK",
                j.get("date", ""), j.get("location", "Remote"),
                salary=sal, description=desc
            ))
    except Exception as e:
        print(f"RemoteOK error: {e}")
    print(f"RemoteOK: {len(jobs)}")
    return jobs


def scrape_jobicy():
    jobs = []
    try:
        r = get("https://jobicy.com/api/v2/remote-jobs?count=100&industries=marketing,customer-service,business")
        if not r: return jobs
        for j in r.json().get("jobs", []):
            if not is_recent(j.get("jobPubDate", "")): continue
            sal = j.get("annualSalaryMin", "")
            sal_str = f"${sal}–${j.get('annualSalaryMax','')}" if sal else ""
            jobs.append(make_job(
                j.get("jobTitle", ""), j.get("companyName", ""),
                j.get("url", ""), "Jobicy",
                j.get("jobPubDate", ""), j.get("jobGeo", "Remote"),
                salary=sal_str
            ))
    except Exception as e:
        print(f"Jobicy error: {e}")
    print(f"Jobicy: {len(jobs)}")
    return jobs


def scrape_himalayas():
    jobs = []
    try:
        r = get("https://himalayas.app/jobs/api?limit=100&remote=true")
        if not r: return jobs
        for j in r.json().get("jobs", []):
            if not is_recent(j.get("createdAt", "")): continue
            sal = ""
            if j.get("salaryMin"):
                sal = f"${j['salaryMin']:,}–${j.get('salaryMax', j['salaryMin']):,}"
            fund = j.get("companyFunding", "")
            fund_str = f"${fund:,.0f}" if isinstance(fund, (int, float)) and fund else str(fund) if fund else ""
            jobs.append(make_job(
                j.get("title", ""), j.get("companyName", ""),
                j.get("applicationLink", j.get("url", "")), "Himalayas",
                j.get("createdAt", ""), j.get("locationRestrictions", "Remote"),
                salary=sal, funding=fund_str,
                company_type=j.get("companySize", "")
            ))
    except Exception as e:
        print(f"Himalayas error: {e}")
    print(f"Himalayas: {len(jobs)}")
    return jobs


def scrape_arbeitnow():
    jobs = []
    try:
        r = get("https://www.arbeitnow.com/api/job-board-api")
        if not r: return jobs
        for j in r.json().get("data", []):
            if not is_recent(j.get("created_at", "")): continue
            desc = j.get("description", "")
            jobs.append(make_job(
                j.get("title", ""), j.get("company_name", ""),
                j.get("url", ""), "Arbeitnow",
                j.get("created_at", ""), j.get("location", "Remote"),
                salary=detect_salary(desc), description=desc
            ))
    except Exception as e:
        print(f"Arbeitnow error: {e}")
    print(f"Arbeitnow: {len(jobs)}")
    return jobs


def scrape_web3career():
    jobs = []
    PATHS = ["/community", "/marketing", "/support", "/customer-service",
             "/ambassador", "/social-media", "/growth", "/partnerships",
             "/moderator", "/operations"]
    for path in PATHS:
        try:
            r = get(f"https://web3.career{path}", scraper=True, timeout=20)
            if not r or r.status_code != 200: continue
            soup = BeautifulSoup(r.text, "lxml")
            for row in soup.select("tr.job_row, div.job-card, article.job"):
                a = row.find("a", href=True)
                if not a: continue
                title = a.get_text(strip=True)
                if not title or len(title) < 5: continue
                href = a["href"]
                link = f"https://web3.career{href}" if href.startswith("/") else href
                company_tag = row.find(class_=lambda c: c and "company" in c.lower())
                company = company_tag.get_text(strip=True) if company_tag else ""
                date_tag = row.find("time")
                date = date_tag.get("datetime", "") if date_tag else ""
                jobs.append(make_job(title, company, link, "Web3.career", date))
        except Exception as e:
            print(f"Web3.career {path}: {e}")
    print(f"Web3.career: {len(jobs)}")
    return jobs


def scrape_the_muse():
    """The Muse — free API, no key needed"""
    jobs = []
    CATEGORIES = ["Marketing%20%26%20PR", "Customer%20Service", "Social%20Media%20%26%20Community",
                  "Business%20%26%20Strategy", "Operations"]
    try:
        for cat in CATEGORIES:
            r = get(f"https://www.themuse.com/api/public/jobs?category={cat}&level=Entry%20Level&level=Mid%20Level&level=Senior%20Level&level=Manager&level=Director&level=VP&level=Executive&page=1&descending=true")
            if not r or r.status_code != 200: continue
            for j in r.json().get("results", []):
                pub = j.get("publication_date", "")
                if not is_recent(pub): continue
                company = j.get("company", {}).get("name", "")
                locations = j.get("locations", [])
                loc = locations[0].get("name", "Remote") if locations else "Remote"
                refs = j.get("refs", {})
                url = refs.get("landing_page", "https://themuse.com/jobs")
                jobs.append(make_job(j.get("name", ""), company, url, "The Muse", pub, loc))
    except Exception as e:
        print(f"The Muse error: {e}")
    print(f"The Muse: {len(jobs)}")
    return jobs


def scrape_hackernews_hiring():
    """HackerNews 'Who is Hiring' — direct from founders, unique source"""
    jobs = []
    try:
        # Get current month's "Who is Hiring" thread
        r = get("https://hacker-news.firebaseio.com/v0/user/whoishiring/submitted.json", timeout=10)
        if not r: return jobs
        ids = r.json()[:1]  # only latest month

        for thread_id in ids:
            tr = get(f"https://hacker-news.firebaseio.com/v0/item/{thread_id}.json", timeout=10)
            if not tr: continue
            item = tr.json()
            if not item or "hiring" not in item.get("title", "").lower(): continue

            kids = item.get("kids", [])[:40]  # top 40 comments only
            for kid_id in kids:
                cr = get(f"https://hacker-news.firebaseio.com/v0/item/{kid_id}.json", timeout=8)
                if not cr: continue
                comment = cr.json()
                if not comment or comment.get("dead") or comment.get("deleted"): continue
                text = comment.get("text", "")
                if not text: continue

                # Parse job from comment
                soup = BeautifulSoup(text, "html.parser")
                plain = soup.get_text(" ")
                lines = [l.strip() for l in plain.split("\n") if l.strip()]
                if not lines: continue

                title_line = lines[0][:100]
                # Extract company (usually "Company | Role | Location")
                parts = re.split(r'\|', title_line)
                if len(parts) >= 2:
                    company = parts[0].strip()
                    title = parts[1].strip() if len(parts) > 1 else title_line
                else:
                    company = ""
                    title = title_line

                # Find URL in comment
                link_tag = soup.find("a", href=True)
                url = link_tag["href"] if link_tag else f"https://news.ycombinator.com/item?id={kid_id}"

                sal = detect_salary(plain)
                visa = detect_visa(plain)
                loc = "Remote" if "remote" in plain.lower() else "See posting"

                date_ts = comment.get("time", 0)
                date_str = datetime.utcfromtimestamp(date_ts).strftime("%Y-%m-%dT%H:%M:%SZ") if date_ts else ""

                if not is_recent(date_str, days=35): continue

                jobs.append(make_job(title, company, url, "HackerNews Hiring",
                                     date_str, loc, salary=sal, visa=visa, description=plain[:200]))
    except Exception as e:
        print(f"HackerNews Hiring error: {e}")
    print(f"HackerNews Hiring: {len(jobs)}")
    return jobs


def scrape_ashby():
    """Ashby ATS — used by OpenAI, Notion, Linear, Cursor, Ramp, Deel, Reddit, Shopify, etc."""
    jobs = []
    COMPANIES = [
        ("openai", "OpenAI"), ("notion", "Notion"), ("linear", "Linear"),
        ("cursor", "Cursor"), ("ramp", "Ramp"), ("deel", "Deel"),
        ("vercel", "Vercel"), ("supabase", "Supabase"), ("replit", "Replit"),
        ("anthropic", "Anthropic"), ("perplexity", "Perplexity"),
        ("brex", "Brex"), ("rippling", "Rippling"), ("mercury", "Mercury"),
        ("figma", "Figma"), ("zapier", "Zapier"),
    ]
    for slug, name in COMPANIES:
        try:
            r = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=10)
            if not r or r.status_code != 200: continue
            data = r.json()
            for j in data.get("jobs", []):
                if not j.get("isListed", True): continue
                loc_info = j.get("location", {})
                loc = loc_info.get("locationStr", "Remote") if isinstance(loc_info, dict) else str(loc_info)
                comp = j.get("compensation", {})
                sal = ""
                if isinstance(comp, dict) and comp.get("summaryComponents"):
                    sal = comp["summaryComponents"][0].get("label", "")
                jobs.append(make_job(
                    j.get("title", ""), name,
                    j.get("jobUrl", f"https://jobs.ashbyhq.com/{slug}"),
                    "Ashby", j.get("publishedAt", ""), loc, salary=sal,
                    company_type="startup"
                ))
        except Exception:
            pass
    print(f"Ashby: {len(jobs)}")
    return jobs


def scrape_greenhouse():
    """Greenhouse ATS — top funded companies"""
    jobs = []
    COMPANIES = [
        ("coinbase", "Coinbase"), ("kraken", "Kraken"), ("gemini", "Gemini"),
        ("polygon", "Polygon"), ("chainlink", "Chainlink"), ("uniswap", "Uniswap"),
        ("opensea", "OpenSea"), ("alchemy", "Alchemy"), ("nansen", "Nansen"),
        ("binance", "Binance"), ("bybit", "Bybit"), ("okx", "OKX"),
        ("stripe", "Stripe"), ("airbnb", "Airbnb"), ("doordash", "DoorDash"),
        ("lyft", "Lyft"), ("instacart", "Instacart"), ("robinhood", "Robinhood"),
        ("plaid", "Plaid"), ("chime", "Chime"), ("brex", "Brex"),
        ("scale-ai", "Scale AI"), ("huggingface", "HuggingFace"),
        ("databricks", "Databricks"), ("snowflake", "Snowflake"),
        ("mongodb", "MongoDB"), ("elastic", "Elastic"), ("hashicorp", "HashiCorp"),
        ("gitlab", "GitLab"), ("cloudflare", "Cloudflare"),
    ]
    for slug, name in COMPANIES:
        try:
            r = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", timeout=10)
            if not r or r.status_code != 200: continue
            for j in r.json().get("jobs", []):
                loc = j.get("location", {}).get("name", "Remote")
                desc = j.get("content", "")
                sal = detect_salary(desc)
                visa = detect_visa(desc)
                jobs.append(make_job(
                    j.get("title", ""), name,
                    j.get("absolute_url", ""), "Greenhouse",
                    j.get("updated_at", ""), loc,
                    salary=sal, visa=visa, description=desc[:200]
                ))
        except Exception:
            pass
    print(f"Greenhouse: {len(jobs)}")
    return jobs


def scrape_lever():
    """Lever ATS — startups"""
    jobs = []
    COMPANIES = [
        ("animoca-brands", "Animoca Brands"), ("magic-eden", "Magic Eden"),
        ("yuga-labs", "Yuga Labs"), ("immutable", "Immutable"),
        ("the-graph", "The Graph"), ("optimism", "Optimism"),
        ("arbitrum", "Arbitrum Foundation"), ("aave", "Aave"),
        ("ledger", "Ledger"), ("metamask", "MetaMask"),
        ("consensys", "ConsenSys"), ("chainalysis", "Chainalysis"),
        ("nansen", "Nansen"), ("alchemy", "Alchemy"),
        ("notion", "Notion"), ("linear", "Linear"),
    ]
    for slug, name in COMPANIES:
        try:
            r = get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=10)
            if not r or r.status_code != 200: continue
            for j in r.json():
                cats = j.get("categories", {})
                loc = cats.get("location", "Remote")
                desc = j.get("descriptionPlain", "")
                sal = detect_salary(desc)
                jobs.append(make_job(
                    j.get("text", ""), name,
                    j.get("hostedUrl", ""), "Lever",
                    "", loc, salary=sal
                ))
        except Exception:
            pass
    print(f"Lever: {len(jobs)}")
    return jobs


def scrape_workingnomads():
    jobs = []
    CATS = ["marketing", "customer-support", "management-finance", "business-development"]
    for cat in CATS:
        try:
            r = get(f"https://www.workingnomads.com/api/exposed_jobs/?category={cat}")
            if not r or r.status_code != 200: continue
            for j in r.json():
                if not is_recent(j.get("pub_date", "")): continue
                jobs.append(make_job(
                    j.get("title", ""), j.get("company", ""),
                    j.get("url", ""), "WorkingNomads",
                    j.get("pub_date", ""), j.get("region", "Remote")
                ))
        except Exception:
            pass
    print(f"WorkingNomads: {len(jobs)}")
    return jobs


def scrape_jobberman():
    """Nigeria's top job board"""
    jobs = []
    try:
        r = get("https://jobicy.com/api/v2/remote-jobs?count=50&geo=nigeria", timeout=12)
        if r and r.status_code == 200:
            for j in r.json().get("jobs", []):
                if not is_recent(j.get("jobPubDate", "")): continue
                jobs.append(make_job(
                    j.get("jobTitle", ""), j.get("companyName", ""),
                    j.get("url", ""), "Nigeria Jobs",
                    j.get("jobPubDate", ""), "Nigeria"
                ))
    except Exception:
        pass
    print(f"Nigeria Jobs: {len(jobs)}")
    return jobs


def scrape_india_jobs():
    """India remote jobs via Jobicy geo filter"""
    jobs = []
    try:
        r = get("https://jobicy.com/api/v2/remote-jobs?count=50&geo=india", timeout=12)
        if r and r.status_code == 200:
            for j in r.json().get("jobs", []):
                if not is_recent(j.get("jobPubDate", "")): continue
                jobs.append(make_job(
                    j.get("jobTitle", ""), j.get("companyName", ""),
                    j.get("url", ""), "India Jobs",
                    j.get("jobPubDate", ""), "India"
                ))
    except Exception:
        pass
    print(f"India Jobs: {len(jobs)}")
    return jobs


# ── Main aggregator ──────────────────────────────────────────────────────────

def get_all_jobs():
    import concurrent.futures
    scrapers = [
        scrape_remotive, scrape_wwr, scrape_remoteok, scrape_jobicy,
        scrape_himalayas, scrape_arbeitnow, scrape_web3career,
        scrape_the_muse, scrape_hackernews_hiring, scrape_ashby,
        scrape_greenhouse, scrape_lever, scrape_workingnomads,
        scrape_jobberman, scrape_india_jobs,
    ]
    all_jobs = []
    seen_ids = set()

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(s): s.__name__ for s in scrapers}
        for fut in concurrent.futures.as_completed(futures, timeout=600):
            try:
                result = fut.result(timeout=90)
                for j in result:
                    if j["id"] not in seen_ids:
                        seen_ids.add(j["id"])
                        all_jobs.append(j)
            except Exception as e:
                print(f"Scraper error: {e}")

    # Sort: hot jobs first, then by date
    all_jobs.sort(key=lambda j: (not j.get("hot"), j.get("date", "") == ""))
    print(f"Total unique jobs: {len(all_jobs)}")
    return all_jobs


# ── Matching & scoring ───────────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "community": ["community", "moderator", "discord", "telegram", "ambassador", "kol",
                  "social media", "engagement", "forum", "galxe", "zealy"],
    "marketing": ["marketing", "growth", "seo", "sem", "content", "brand", "pr ",
                  "influencer", "campaign", "copywriter", "email marketing"],
    "support": ["customer support", "customer success", "support specialist", "help desk",
                "customer service", "technical support", "cx ", "client success"],
    "tech": ["engineer", "developer", "frontend", "backend", "fullstack", "devops",
             "software", "python", "javascript", "typescript", "rust", "golang"],
    "product": ["product manager", "product designer", "ux", "ui ", "researcher"],
    "design": ["designer", "graphic", "figma", "creative", "visual", "illustrat"],
    "sales": ["sales", "account executive", "business development", "bd ", "partnerships",
              "revenue", "closing", "quota"],
    "finance": ["finance", "accounting", "analyst", "controller", "cfo", "tax"],
    "operations": ["operations", "ops ", "project manager", "coordinator", "logistics",
                   "supply chain", "hr ", "recruiting", "talent"],
    "executive": ["ceo", "cto", "cmo", "coo", "chief", "vp ", "vice president",
                  "head of", "director", "svp"],
    "web3": ["web3", "blockchain", "crypto", "defi", "nft", "dao", "solidity",
             "smart contract", "protocol", "dapp", "layer 2", "l2"],
    "all": [],
}

SENIORITY_KEYWORDS = {
    "entry": ["junior", "entry", "associate", "intern", "trainee", "graduate"],
    "mid": ["mid", "intermediate", "ii", "2", "experienced"],
    "senior": ["senior", "sr.", "sr ", "lead", "principal", "staff"],
    "manager": ["manager", "management"],
    "director": ["director", "head of"],
    "csuite": ["ceo", "cto", "cmo", "coo", "chief", "vp ", "svp", "evp", "president"],
    "all": [],
}

LOCATION_MAP = {
    "usa": ["usa", "united states", "us ", "america", "new york", "san francisco", "remote us"],
    "uk": ["uk", "united kingdom", "london", "england", "britain"],
    "india": ["india", "bangalore", "mumbai", "delhi", "hyderabad", "remote india"],
    "europe": ["europe", "european", "germany", "france", "spain", "amsterdam", "berlin"],
    "nigeria": ["nigeria", "lagos", "abuja", "remote nigeria"],
    "japan": ["japan", "tokyo"],
    "sea": ["southeast asia", "singapore", "indonesia", "vietnam", "philippines", "malaysia"],
    "middleeast": ["dubai", "uae", "middle east", "qatar", "saudi"],
    "remote": ["remote", "anywhere", "worldwide", "global", "distributed"],
    "worldwide": [],  # matches everything
}


def matches_category(job, category):
    if category == "all":
        return True
    kws = CATEGORY_KEYWORDS.get(category, [])
    if not kws:
        return True
    text = (job["title"] + " " + job.get("description", "")).lower()
    return any(k in text for k in kws)


def matches_seniority(job, seniority):
    if seniority == "all":
        return True
    kws = SENIORITY_KEYWORDS.get(seniority, [])
    if not kws:
        return True
    title = job["title"].lower()
    return any(k in title for k in kws)


def matches_location(job, location_key):
    if location_key in ("worldwide", "all", ""):
        return True
    if location_key == "remote":
        loc = job.get("location", "").lower()
        return any(k in loc for k in ["remote", "anywhere", "worldwide", "global"])
    kws = LOCATION_MAP.get(location_key, [])
    if not kws:
        return True
    loc = job.get("location", "").lower()
    if any(k in loc for k in ["remote", "worldwide", "anywhere"]):
        return True  # remote jobs match any location
    return any(k in loc for k in kws)


def matches_keywords(job, keywords_str):
    if not keywords_str:
        return True
    kws = [k.strip().lower() for k in keywords_str.split(",") if k.strip()]
    if not kws:
        return True
    text = (job["title"] + " " + job.get("description", "")).lower()
    return any(k in text for k in kws)


def matches_company_type(job, ctype):
    if ctype == "any":
        return True
    if ctype == "startup":
        return job.get("company_type") in ["startup", "seed", "early"]
    return True


def matches_user(job, user):
    return (
        matches_category(job, user.get("category", "all")) and
        matches_seniority(job, user.get("seniority", "all")) and
        matches_location(job, user.get("location_key", "worldwide")) and
        matches_keywords(job, user.get("keywords", "")) and
        matches_company_type(job, user.get("company_type", "any"))
    )


def score(title, keywords_str=""):
    """Score job relevance 0-100"""
    s = 50
    title_l = title.lower()
    if keywords_str:
        kws = [k.strip().lower() for k in keywords_str.split(",") if k.strip()]
        s += sum(15 for k in kws if k in title_l)
    return min(100, s)
