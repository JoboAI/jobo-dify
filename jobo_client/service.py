"""
The five Jobo operations behind the plugin's tools.

Each method turns tool arguments into one Jobo API request and returns a
`Result`: text a model can read and a small JSON object for workflow variables.
Nothing here imports the Dify SDK, so it is tested without it.
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote
from uuid import UUID

from jobo_client.client import JoboClient, Reply
from jobo_client.errors import JoboAPIError, JoboNotFoundError
from jobo_client.format import (
    EMPTY_SEARCH,
    flatten_taxonomy,
    format_company_suggestions,
    format_filter_values,
    format_job_document,
    format_job_summary,
    format_location_suggestions,
    format_occupation_matches,
    job_metadata,
    match_occupations,
    search_header,
    search_notes,
)

API_MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 5
#: Hard cap on jobs requested per search. Every job returned is billed, so a
#: larger page_size from a model is reduced to this.
MAX_PAGE_SIZE = 25
_TAXONOMY_TTL_SECONDS = 600.0
#: The occupation taxonomy, per base URL and API key, for every service in
#: this process. Each tool call builds a new service, so a cache on the
#: service would never be hit. Keyed per key so a key the API would reject is
#: not served another key's copy. The plugin runtime may run tool calls on
#: several threads, hence the lock.
_TAXONOMY_CACHE: Dict[str, Tuple[float, List[Dict[str, str]]]] = {}
_TAXONOMY_LOCK = threading.Lock()
_TAXONOMY_MAX_ENTRIES = 64

WORK_MODELS = ("remote", "hybrid", "onsite")
EMPLOYMENT_TYPES = (
    "full-time",
    "part-time",
    "contract",
    "internship",
    "freelance",
    "temporary",
)
EXPERIENCE_LEVELS = ("intern", "entry", "mid", "senior", "lead", "executive")
COMPANY_CATEGORIES = (
    "b2b",
    "b2c",
    "b2b2c",
    "b2g",
    "saas",
    "marketplace",
    "e-commerce",
    "service-provider",
    "hardware",
    "agency",
    "nonprofit",
    "government",
    "education",
)
SORTS = ("relevance", "discovered_asc", "discovered_desc")
FILTER_FACETS = (
    "sources",
    "industries",
    "skills",
    "company_categories",
    "job_categories",
    "job_subcategories",
    "occupations",
)

_SANDBOX_NOTE = (
    "a sandbox API key (jbe_test_...) serves job search and job details only"
)


class ToolInputError(ValueError):
    """A tool argument is invalid. The message says how to fix it."""


@dataclass
class Result:
    """What a tool returns: readable text plus structured data."""

    text: str
    data: Dict[str, Any] = field(default_factory=dict)


def split_values(value: Any, separator: str = ",") -> List[str]:
    """
    A string argument as a list of unique, trimmed, non-empty values.

    Dify tool parameters are plain strings, so a list is written as one string:
    comma-separated for fixed vocabularies and semicolon-separated for places
    and company names, which can contain commas themselves.
    """
    if value is None:
        return []
    raw = value if isinstance(value, (list, tuple)) else str(value).split(separator)
    seen: List[str] = []
    for item in raw:
        text = str(item).strip() if item is not None else ""
        if text and text not in seen:
            seen.append(text)
    return seen


def _enum_list(name: str, value: Any, allowed: Tuple[str, ...]) -> List[str]:
    values = [v.lower() for v in split_values(value)]
    unknown = [v for v in values if v not in allowed]
    if unknown:
        raise ToolInputError(
            f"Unknown {name} value(s) {unknown}. Allowed: {', '.join(allowed)}. "
            "An unknown value would match no jobs."
        )
    return values


def _timestamp(name: str, value: Any) -> Optional[str]:
    if value is None or not str(value).strip():
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ToolInputError(
            f"{name} must be an ISO 8601 timestamp such as 2026-01-31 or "
            f"2026-01-31T09:00:00Z, got {value!r}."
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")


def _boolean(name: str, value: Any) -> Optional[bool]:
    """A yes/no argument, or None when it was not given."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise ToolInputError(f"{name} must be true or false, got {value!r}.")


def _whole_number(name: str, value: Any, default: int) -> int:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ToolInputError(f"{name} must be a whole number, got {value!r}.") from exc
    return int(number)


def _pair(include: List[str], exclude: List[str]) -> Dict[str, List[str]]:
    pair: Dict[str, List[str]] = {}
    if include:
        pair["include"] = include
    if exclude:
        pair["exclude"] = exclude
    return pair


def _items(reply: Reply, key: str) -> List[Dict[str, Any]]:
    payload = reply.data if isinstance(reply.data, dict) else {}
    return [i for i in (payload.get(key) or []) if isinstance(i, dict)]


def _is_job_not_found(error: JoboNotFoundError) -> bool:
    """
    Whether the API itself said that no job has this id.

    `GET /api/jobs/{id}` answers an unknown id with the problem "Job not
    found". Every other 404 (a wrong base URL, a proxy, a sandbox gap) means
    something is misconfigured and must not be read as "no such job".
    """
    if error.code == "job_not_found":
        return True
    title = error.body.get("title") if isinstance(error.body, dict) else None
    return isinstance(title, str) and title.strip().lower() == "job not found"


class JoboService:
    """The five Jobo operations. Search is billed per job; the rest are free."""

    def __init__(self, client: JoboClient, max_page_size: int = MAX_PAGE_SIZE) -> None:
        if not 1 <= max_page_size <= API_MAX_PAGE_SIZE:
            raise ValueError(
                f"max_page_size must be between 1 and {API_MAX_PAGE_SIZE}."
            )
        self.client = client
        self.max_page_size = max_page_size

    # ------------------------------------------------------------ search_jobs

    def search_request(self, args: Mapping[str, Any]) -> Tuple[Dict[str, Any], Optional[int]]:
        """The request body for a search, and the cap applied to page_size if any."""
        a = args
        body: Dict[str, Any] = {}
        query = str(a.get("query") or "").strip()
        if query:
            body["queries"] = [query]
        locations = split_values(a.get("location"), ";")
        if locations:
            body["locations"] = locations
        sources = [s.lower() for s in split_values(a.get("sources"))]
        if sources:
            body["sources"] = sources
        for wire, values in (
            ("work_models", _enum_list("work_model", a.get("work_model"), WORK_MODELS)),
            (
                "employment_types",
                _enum_list("employment_type", a.get("employment_type"), EMPLOYMENT_TYPES),
            ),
            (
                "experience_levels",
                _enum_list(
                    "experience_level", a.get("experience_level"), EXPERIENCE_LEVELS
                ),
            ),
            ("languages", [v.lower() for v in split_values(a.get("language"))]),
        ):
            if values:
                body[wire] = values
        pairs = {
            "skills": _pair(
                split_values(a.get("skills")), split_values(a.get("exclude_skills"))
            ),
            "companies": _pair(
                split_values(a.get("companies"), ";"),
                split_values(a.get("exclude_companies"), ";"),
            ),
            "industries": _pair(
                split_values(a.get("industries"), ";"),
                split_values(a.get("exclude_industries"), ";"),
            ),
            "company_categories": _pair(
                _enum_list(
                    "company_categories",
                    a.get("company_categories"),
                    COMPANY_CATEGORIES,
                ),
                _enum_list(
                    "exclude_company_categories",
                    a.get("exclude_company_categories"),
                    COMPANY_CATEGORIES,
                ),
            ),
            "job_categories": _pair(
                split_values(a.get("job_categories"), ";"),
                split_values(a.get("exclude_job_categories"), ";"),
            ),
            "job_subcategories": _pair(
                split_values(a.get("job_subcategories"), ";"),
                split_values(a.get("exclude_job_subcategories"), ";"),
            ),
            "occupation_ids": _pair(
                split_values(a.get("occupation_ids")),
                split_values(a.get("exclude_occupation_ids")),
            ),
        }
        body.update({k: v for k, v in pairs.items() if v})
        search_description = _boolean(
            "search_description", a.get("search_description")
        )
        if search_description is not None:
            body["search_description"] = search_description
        salary: Dict[str, int] = {}
        minimum = _whole_number("min_salary_usd", a.get("min_salary_usd"), 0)
        maximum = _whole_number("max_salary_usd", a.get("max_salary_usd"), 0)
        if minimum:
            salary["min"] = minimum
        if maximum:
            salary["max"] = maximum
        if salary:
            body["salary_usd"] = salary
        for key in (
            "posted_after",
            "posted_before",
            "discovered_after",
            "discovered_before",
        ):
            stamp = _timestamp(key, a.get(key))
            if stamp:
                body[key] = stamp
        sort = str(a.get("sort") or "").strip().lower()
        if sort:
            if sort not in SORTS:
                raise ToolInputError(f"Unknown sort {sort!r}. Allowed: {', '.join(SORTS)}.")
            if sort != "relevance":
                body["sort"] = sort
        page = max(_whole_number("page", a.get("page"), 1), 1)
        requested = max(_whole_number("page_size", a.get("page_size"), DEFAULT_PAGE_SIZE), 1)
        page_size = min(requested, self.max_page_size)
        body["page"] = page
        body["page_size"] = page_size
        return body, (page_size if page_size < requested else None)

    def search_jobs(self, args: Mapping[str, Any]) -> Result:
        """Search live jobs. BILLED per job returned."""
        body, capped = self.search_request(args)
        reply = self.client.request("POST", "/api/jobs/search", json=body)
        payload = reply.data if isinstance(reply.data, dict) else {}
        jobs = [j for j in (payload.get("jobs") or []) if isinstance(j, dict)]
        notes = search_notes(payload)
        if capped is not None:
            notes.append(
                f"Note: page_size was capped at {capped}, this tool's maximum, "
                "because every returned job is billed."
            )
        lines = [search_header(payload, len(jobs)) if jobs else EMPTY_SEARCH, *notes]
        lines.extend(format_job_summary(job, i) for i, job in enumerate(jobs, start=1))
        summary = {
            "total": payload.get("total"),
            "page": payload.get("page"),
            "page_size": payload.get("page_size"),
            "total_pages": payload.get("total_pages"),
            **reply.usage,
        }
        data = {
            "summary": {k: v for k, v in summary.items() if v is not None},
            "jobs": [job_metadata(job) for job in jobs],
        }
        return Result("\n".join(lines), data)

    # -------------------------------------------------------------- get_job

    def get_job(self, job_id: Any, include_description: bool = True) -> Result:
        """One job by id. Free."""
        text = str(job_id or "").strip()
        try:
            path = f"/api/jobs/{quote(str(UUID(text)), safe='')}"
        except ValueError:
            return Result(
                f'"{text}" is not a Jobo job id. Job ids are UUIDs: the `ID` '
                "values search_jobs returns.",
                {"found": False},
            )
        try:
            reply = self.client.request("GET", path)
        except JoboNotFoundError as error:
            if _is_job_not_found(error):
                return Result(
                    f'No job exists with id "{text}". It may have closed. '
                    "Job ids are the `ID` values search_jobs returns.",
                    {"found": False},
                )
            raise
        job = reply.data if isinstance(reply.data, dict) else {}
        return Result(
            format_job_document(job, include_description=include_description),
            {"found": True, "job": job_metadata(job)},
        )

    # ------------------------------------------------ lookups (always free)

    @staticmethod
    def _sandbox_unavailable(
        error: JoboAPIError, what: str, advice: str
    ) -> Result:
        if isinstance(error, JoboNotFoundError) and error.not_available_in_sandbox:
            return Result(
                f"{what} cannot be looked up here: {_SANDBOX_NOTE}. Do not call "
                f"this tool again. {advice}",
                {"available": False},
            )
        raise error

    def find_companies(self, query: Any, limit: Any = 5) -> Result:
        """Company name or domain to company ids. Free."""
        text = str(query or "").strip()
        params = {"q": text, "limit": min(max(_whole_number("limit", limit, 5), 1), 20)}
        try:
            reply = self.client.request(
                "GET", "/api/connectors/companies/suggest", params=params
            )
        except JoboAPIError as error:
            return self._sandbox_unavailable(
                error,
                "Companies",
                "Pass the company's name or website domain as the `companies` "
                "filter of search_jobs instead.",
            )
        suggestions = _items(reply, "suggestions")
        return Result(
            format_company_suggestions(text, suggestions),
            {"query": text, "companies": suggestions},
        )

    def _occupation_rows(self) -> List[Dict[str, str]]:
        key = self.client.cache_key()
        with _TAXONOMY_LOCK:
            cached = _TAXONOMY_CACHE.get(key)
        if cached is not None and time.monotonic() - cached[0] <= _TAXONOMY_TTL_SECONDS:
            return cached[1]
        # Fetched outside the lock: two calls that miss at once both fetch,
        # which is cheaper than making every other call wait on the network.
        rows = flatten_taxonomy(self.client.request("GET", "/api/occupations").data)
        with _TAXONOMY_LOCK:
            _TAXONOMY_CACHE[key] = (time.monotonic(), rows)
            while len(_TAXONOMY_CACHE) > _TAXONOMY_MAX_ENTRIES:
                oldest = min(_TAXONOMY_CACHE, key=lambda k: _TAXONOMY_CACHE[k][0])
                del _TAXONOMY_CACHE[oldest]
        return rows

    def find_filter_values(self, facet: Any, query: Any = None, limit: Any = 20) -> Result:
        """The values a search filter accepts, with live job counts. Free."""
        name = str(facet or "").strip().lower()
        if name not in FILTER_FACETS:
            raise ToolInputError(
                f"Unknown facet {facet!r}. Allowed: {', '.join(FILTER_FACETS)}."
            )
        text = str(query or "").strip()
        count = min(max(_whole_number("limit", limit, 20), 1), 50)
        try:
            if name == "occupations" and text:
                matches = match_occupations(self._occupation_rows(), text, count)
                return Result(
                    format_occupation_matches(text, matches),
                    {"facet": name, "query": text, "values": matches},
                )
            params: Dict[str, Any] = {"limit": count}
            if text:
                params["q"] = text
            reply = self.client.request(
                "GET",
                f"/api/connectors/filter-options/{quote(name, safe='')}",
                params=params,
            )
        except JoboAPIError as error:
            return self._sandbox_unavailable(
                error,
                "Filter values",
                "Call search_jobs without the lookup; work_model, employment_type, "
                "experience_level and company_categories list their values in that "
                "tool's arguments.",
            )
        options = _items(reply, "options")
        return Result(
            format_filter_values(name, text, options),
            {"facet": name, "query": text, "values": options},
        )

    def find_locations(self, query: Any, limit: Any = 5) -> Result:
        """Place name to the locations search_jobs takes. Free typeahead."""
        text = str(query or "").strip()
        params = {"q": text, "limit": min(max(_whole_number("limit", limit, 5), 1), 10)}
        try:
            reply = self.client.request(
                "GET", "/api/connectors/locations/suggest", params=params
            )
        except JoboAPIError as error:
            return self._sandbox_unavailable(
                error,
                "Places",
                "Pass the place name as the `location` filter of search_jobs as it "
                "is: the search resolves free-form locations itself.",
            )
        suggestions = _items(reply, "suggestions")
        return Result(
            format_location_suggestions(text, suggestions),
            {"query": text, "locations": suggestions},
        )
