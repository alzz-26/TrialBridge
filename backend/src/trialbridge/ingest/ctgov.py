"""ClinicalTrials.gov API v2 client and schema normaliser.

API docs: https://clinicaltrials.gov/data-api/api
No key needed. We normalise each study into the registry-agnostic `trials`
schema so that CTRI records (Phase 2) can share the same downstream pipeline.
"""

import re
import time
from collections.abc import Iterable, Iterator

import httpx

from trialbridge.config import CTGOV_API, USER_AGENT

FIELDS = ",".join([
    "NCTId", "BriefTitle", "OfficialTitle", "OverallStatus", "Phase", "Condition", "Keyword",
    "InterventionName", "BriefSummary", "EligibilityCriteria", "MinimumAge", "MaximumAge",
    "Sex", "HealthyVolunteers", "LocationCountry", "LastUpdatePostDate",
])

_AGE_RE = re.compile(r"([\d.]+)\s*(year|month|week|day|hour|minute)", re.I)
_AGE_UNIT_TO_YEARS = {"year": 1, "month": 1 / 12, "week": 1 / 52.18, "day": 1 / 365.25,
                      "hour": 1 / 8766, "minute": 1 / 525960}


def parse_age(text: str | None) -> float | None:
    """'18 Years' -> 18.0, '6 Months' -> 0.5, None/'N/A' -> None."""
    if not text:
        return None
    m = _AGE_RE.search(text)
    if not m:
        return None
    return round(float(m.group(1)) * _AGE_UNIT_TO_YEARS[m.group(2).lower()], 3)


def normalise(study: dict) -> dict:
    p = study.get("protocolSection", {})
    ident = p.get("identificationModule", {})
    status = p.get("statusModule", {})
    elig = p.get("eligibilityModule", {})
    locations = p.get("contactsLocationsModule", {}).get("locations", []) or []
    return {
        "trial_id": ident.get("nctId"),
        "source": "ctgov",
        "title": ident.get("briefTitle"),
        "official_title": ident.get("officialTitle"),
        "status": status.get("overallStatus"),
        "phase": ", ".join(p.get("designModule", {}).get("phases", []) or []) or None,
        "conditions": p.get("conditionsModule", {}).get("conditions", []) or [],
        "keywords": p.get("conditionsModule", {}).get("keywords", []) or [],
        "interventions": [i.get("name") for i in p.get("armsInterventionsModule", {}).get("interventions", []) or []],
        "summary": p.get("descriptionModule", {}).get("briefSummary"),
        "eligibility": elig.get("eligibilityCriteria"),
        "min_age_years": parse_age(elig.get("minimumAge")),
        "max_age_years": parse_age(elig.get("maximumAge")),
        "sex": elig.get("sex", "ALL"),
        "healthy_volunteers": int(bool(elig.get("healthyVolunteers"))),
        "countries": sorted({loc.get("country") for loc in locations if loc.get("country")}),
        "last_updated": status.get("lastUpdatePostDateStruct", {}).get("date"),
    }


class CTGovClient:
    def __init__(self, timeout: float = 60.0, pause: float = 0.3):
        self.http = httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})
        self.pause = pause  # be polite to the public API

    def _get(self, params: dict) -> dict:
        for attempt in range(5):
            try:
                r = self.http.get(CTGOV_API, params=params)
                if r.status_code == 429 or r.status_code >= 500:
                    raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
                r.raise_for_status()
                return r.json()
            except (httpx.TransportError, httpx.HTTPStatusError):
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("unreachable")

    def search(self, condition: str | None = None, term: str | None = None,
               status: str | None = "RECRUITING", limit: int = 200) -> Iterator[dict]:
        """Yield normalised trials matching a condition / free-text term."""
        params = {"fields": FIELDS, "pageSize": min(limit, 1000), "format": "json"}
        if condition:
            params["query.cond"] = condition
        if term:
            params["query.term"] = term
        if status:
            params["filter.overallStatus"] = status
        n = 0
        while n < limit:
            data = self._get(params)
            for s in data.get("studies", []):
                yield normalise(s)
                n += 1
                if n >= limit:
                    return
            token = data.get("nextPageToken")
            if not token:
                return
            params["pageToken"] = token
            time.sleep(self.pause)

    def by_ids(self, nct_ids: Iterable[str], batch: int = 100) -> Iterator[dict]:
        """Yield normalised trials for an explicit list of NCT ids (any status)."""
        ids = list(nct_ids)
        for i in range(0, len(ids), batch):
            chunk = ids[i:i + batch]
            data = self._get({"fields": FIELDS, "filter.ids": ",".join(chunk),
                              "pageSize": len(chunk), "format": "json"})
            for s in data.get("studies", []):
                yield normalise(s)
            time.sleep(self.pause)
