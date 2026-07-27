"""Optional official/licensed job API adapters."""
import os

import requests

from api import logger
from api.jobs import make_job


TIMEOUT = 15
ADZUNA_APP_ID = (
    os.environ.get("ADZUNA_APP_ID")
    or os.environ.get("ADZUNA_ID", "")
)

ADZUNA_APP_KEY = (
    os.environ.get("ADZUNA_APP_KEY")
    or os.environ.get("ADZUNA_KEY", "")
)
ADZUNA_COUNTRIES = [
    item.strip().lower()
    for item in os.environ.get("ADZUNA_COUNTRIES", "in,us,gb,ca,au").split(",")
    if item.strip()
]
USAJOBS_API_KEY = os.environ.get("USAJOBS_API_KEY", "")
USAJOBS_USER_AGENT = os.environ.get("USAJOBS_USER_AGENT", "")


def _adzuna_work_mode(job):
    text = " ".join(
        [
            str(job.get("title", "")),
            str(job.get("description", "")),
            str(job.get("location", {}).get("display_name", "")),
        ]
    ).lower()
    if "hybrid" in text:
        return "hybrid"
    if "remote" in text or "work from home" in text:
        return "remote"
    return "onsite"


def scrape_adzuna():
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return []
    jobs = []
    for country in ADZUNA_COUNTRIES:
        try:
            response = requests.get(
                f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
                params={
                    "app_id": ADZUNA_APP_ID,
                    "app_key": ADZUNA_APP_KEY,
                    "results_per_page": 50,
                    "max_days_old": 7,
                    "sort_by": "date",
                    "content-type": "application/json",
                },
                headers={"Accept": "application/json"},
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            for item in response.json().get("results", []):
                company = (item.get("company") or {}).get("display_name", "")
                location = (item.get("location") or {}).get("display_name", "")
                category = (item.get("category") or {}).get("label", "")
                salary_min = item.get("salary_min")
                salary_max = item.get("salary_max")
                salary = ""
                if salary_min or salary_max:
                    salary = f"{salary_min or '?'} - {salary_max or '?'}"
                contract_time = (item.get("contract_time") or "").lower()
                employment_type = {
                    "full_time": "full_time",
                    "part_time": "part_time",
                }.get(contract_time, "unknown")
                jobs.append(
                    make_job(
                        item.get("title", ""),
                        company,
                        item.get("redirect_url", ""),
                        f"Adzuna {country.upper()}",
                        item.get("created", ""),
                        location,
                        item.get("description", ""),
                        salary,
                        work_mode=_adzuna_work_mode(item),
                        employment_type=employment_type,
                        category=category,
                        discovery_method="adzuna_api",
                    )
                )
        except Exception as exc:
            logger.error(f"Adzuna [{country}] failed: {exc}")
    logger.scraper_result("Adzuna", len(jobs))
    return jobs


def _usajobs_location(descriptor):
    locations = descriptor.get("PositionLocation") or []
    names = [item.get("LocationName", "") for item in locations if item.get("LocationName")]
    return ", ".join(names[:3]) or "United States"


def scrape_usajobs():
    if not USAJOBS_API_KEY or not USAJOBS_USER_AGENT:
        return []
    jobs = []
    try:
        response = requests.get(
            "https://data.usajobs.gov/api/search",
            params={
                "DatePosted": 7,
                "ResultsPerPage": 250,
                "SortField": "opendate",
                "SortDirection": "Desc",
            },
            headers={
                "Host": "data.usajobs.gov",
                "User-Agent": USAJOBS_USER_AGENT,
                "Authorization-Key": USAJOBS_API_KEY,
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        items = (
            response.json()
            .get("SearchResult", {})
            .get("SearchResultItems", [])
        )
        for item in items:
            descriptor = item.get("MatchedObjectDescriptor", {})
            details = descriptor.get("UserArea", {}).get("Details", {})
            salary = ""
            minimum = descriptor.get("PositionRemuneration")
            if minimum:
                pay = minimum[0]
                salary = (
                    f"{pay.get('MinimumRange', '?')} - "
                    f"{pay.get('MaximumRange', '?')} "
                    f"{pay.get('RateIntervalCode', '')}"
                ).strip()
            remote = str(details.get("RemoteIndicator", "")).lower() == "true"
            jobs.append(
                make_job(
                    descriptor.get("PositionTitle", ""),
                    descriptor.get("OrganizationName", "US Federal Government"),
                    descriptor.get("PositionURI", ""),
                    "USAJOBS",
                    descriptor.get("PublicationStartDate", ""),
                    _usajobs_location(descriptor),
                    descriptor.get("QualificationSummary", ""),
                    salary,
                    work_mode="remote" if remote else "onsite",
                    employment_type="full_time",
                    category="government",
                    experience=details.get("JobSummary", ""),
                    discovery_method="usajobs_api",
                )
            )
    except Exception as exc:
        logger.error(f"USAJOBS failed: {exc}")
    logger.scraper_result("USAJOBS", len(jobs))
    return jobs
