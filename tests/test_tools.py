"""Each tool: request shape, auth header, error mapping, page and limit caps. No network."""

import json
import re
from typing import Any, Dict, List

import httpx
import pytest

from jobo_client.glue import JoboToolError
from tests.conftest import JOB, JOB_ID, KEY, reply
from tools.find_companies import FindCompaniesTool
from tools.find_filter_values import FindFilterValuesTool
from tools.find_locations import FindLocationsTool
from tools.get_job import GetJobTool
from tools.list_hiring_signals import ListHiringSignalsTool
from tools.search_jobs import SearchJobsTool

CREDS = {"jobo_api_key": KEY}


def run(tool_cls, params: Dict[str, Any], creds=CREDS) -> List[Any]:
    """Invoke a tool the way Dify does and return its messages."""
    return list(tool_cls.from_credentials(dict(creds)).invoke(tool_parameters=params))


def texts(messages) -> str:
    return "\n".join(
        m.message.text for m in messages if m.type.value == "text"
    )


def json_of(messages) -> Dict[str, Any]:
    (found,) = [m for m in messages if m.type.value == "json"]
    return found.message.json_object


SEARCH_RESPONSE = {
    "jobs": [JOB],
    "total": 1234,
    "page": 1,
    "page_size": 5,
    "total_pages": 247,
}
BILLING = {"X-Credits-Deducted": "15", "X-Credits-Balance": "4985"}


# ------------------------------------------------------------------ search_jobs


def test_search_request_shape_and_auth_header(api):
    mock = api(reply(200, SEARCH_RESPONSE, BILLING))
    messages = run(
        SearchJobsTool,
        {
            "query": "backend engineer",
            "location": "Berlin, Germany; Remote",
            "work_model": "Remote, hybrid",
            "skills": "Python, Go",
            "exclude_skills": "PHP",
            "companies": "stripe.com; Acme, Inc.",
            "min_salary_usd": 90000.0,
            "posted_after": "2026-11-01",
            "sort": "discovered_desc",
        },
    )
    request = mock.last
    assert request.method == "POST"
    assert str(request.url) == "https://connect.jobo.world/api/jobs/search"
    assert request.headers["X-Api-Key"] == KEY
    assert request.headers["X-Jobo-Client"] == "dify"
    assert mock.body == {
        "queries": ["backend engineer"],
        "locations": ["Berlin, Germany", "Remote"],
        "work_models": ["remote", "hybrid"],
        "skills": {"include": ["Python", "Go"], "exclude": ["PHP"]},
        "companies": {"include": ["stripe.com", "Acme, Inc."]},
        "salary_usd": {"min": 90000},
        "posted_after": "2026-11-01T00:00:00Z",
        "sort": "discovered_desc",
        "page": 1,
        "page_size": 5,
    }
    text = texts(messages)
    assert "1,234 matching jobs; showing 1" in text
    assert "Senior Backend Engineer" in text
    data = json_of(messages)
    assert data["summary"]["total"] == 1234
    assert data["summary"]["credits_deducted"] == 15
    assert data["jobs"][0]["id"] == JOB_ID
    assert KEY not in json.dumps(data) + text


def test_search_sends_the_exclude_lists_subcategories_and_discovery_window(api):
    mock = api(reply(200, SEARCH_RESPONSE))
    run(
        SearchJobsTool,
        {
            "industries": "Software; Banking",
            "exclude_industries": "Gambling",
            "company_categories": "saas",
            "exclude_company_categories": "Agency, nonprofit",
            "job_categories": "Healthcare",
            "exclude_job_categories": "Sales; Retail",
            "job_subcategories": "Nursing",
            "exclude_job_subcategories": "Home Care",
            "occupation_ids": "occ-1",
            "exclude_occupation_ids": "occ-2, occ-3",
            "discovered_after": "2026-11-01",
            "discovered_before": "2026-11-20T12:00:00Z",
            "search_description": False,
        },
    )
    body = mock.body
    assert body["industries"] == {"include": ["Software", "Banking"], "exclude": ["Gambling"]}
    assert body["company_categories"] == {
        "include": ["saas"],
        "exclude": ["agency", "nonprofit"],
    }
    assert body["job_categories"] == {"include": ["Healthcare"], "exclude": ["Sales", "Retail"]}
    assert body["job_subcategories"] == {"include": ["Nursing"], "exclude": ["Home Care"]}
    assert body["occupation_ids"] == {"include": ["occ-1"], "exclude": ["occ-2", "occ-3"]}
    assert body["discovered_after"] == "2026-11-01T00:00:00Z"
    assert body["discovered_before"] == "2026-11-20T12:00:00Z"
    assert body["search_description"] is False


def test_search_sends_an_exclude_list_on_its_own(api):
    mock = api(reply(200, SEARCH_RESPONSE))
    run(SearchJobsTool, {"exclude_job_subcategories": "Nursing"})
    assert mock.body["job_subcategories"] == {"exclude": ["Nursing"]}


def test_search_leaves_search_description_to_the_api_when_not_given(api):
    mock = api(reply(200, SEARCH_RESPONSE))
    run(SearchJobsTool, {"query": "nurse"})
    assert "search_description" not in mock.body


def test_search_defaults_to_a_small_page(api):
    mock = api(reply(200, SEARCH_RESPONSE))
    run(SearchJobsTool, {"query": "nurse"})
    assert mock.body["page_size"] == 5
    assert mock.body["page"] == 1


def test_search_page_size_is_capped_at_25_and_the_cap_is_reported(api):
    mock = api(reply(200, SEARCH_RESPONSE))
    messages = run(SearchJobsTool, {"query": "nurse", "page_size": 100.0})
    assert mock.body["page_size"] == 25
    assert "capped at 25" in texts(messages)


def test_search_page_size_under_the_cap_is_kept_and_not_reported(api):
    mock = api(reply(200, SEARCH_RESPONSE))
    messages = run(SearchJobsTool, {"query": "nurse", "page_size": 10})
    assert mock.body["page_size"] == 10
    assert "capped" not in texts(messages)


def test_search_empty_result_is_a_message_not_an_error(api):
    api(reply(200, {"jobs": [], "total": 0, "page": 1, "page_size": 5, "total_pages": 0}))
    messages = run(SearchJobsTool, {"query": "zzzz"})
    assert "No jobs matched" in texts(messages)
    assert json_of(messages)["jobs"] == []


@pytest.mark.parametrize(
    "params, fragment",
    [
        ({"work_model": "office"}, "Unknown work_model"),
        ({"employment_type": "gig"}, "Unknown employment_type"),
        ({"sort": "newest"}, "Unknown sort"),
        ({"posted_after": "last week"}, "posted_after must be an ISO 8601"),
        ({"discovered_before": "yesterday"}, "discovered_before must be an ISO 8601"),
        ({"exclude_company_categories": "startup"}, "Unknown exclude_company_categories"),
        ({"search_description": "maybe"}, "search_description must be true or false"),
        ({"page_size": "many"}, "page_size must be a whole number"),
    ],
)
def test_search_invalid_arguments_fail_before_any_request(api, params, fragment):
    mock = api(reply(200, SEARCH_RESPONSE))
    with pytest.raises(JoboToolError, match=fragment):
        run(SearchJobsTool, params)
    assert mock.requests == []


def test_search_401_maps_to_an_invalid_key_message(api):
    api(reply(401, {"title": "Unauthorized"}))
    with pytest.raises(JoboToolError) as raised:
        run(SearchJobsTool, {"query": "nurse"})
    assert "rejected the API key" in str(raised.value)
    assert KEY not in str(raised.value)


def test_search_402_maps_to_insufficient_credits_and_is_not_retried(api):
    mock = api(
        reply(
            402,
            {
                "code": "insufficient_credits",
                "title": "Payment required",
                "top_up_url": "https://enterprise.jobo.world/credits?topup=1",
            },
        )
    )
    with pytest.raises(JoboToolError) as raised:
        run(SearchJobsTool, {"query": "nurse"})
    message = str(raised.value)
    assert "HTTP 402" in message
    assert "https://enterprise.jobo.world/credits?topup=1" in message
    assert "smaller page_size" in message
    assert len(mock.requests) == 1


def test_search_429_maps_to_a_rate_limit_message(api):
    api(reply(429, {"title": "Too many requests"}, {"Retry-After": "90"}))
    with pytest.raises(JoboToolError) as raised:
        run(SearchJobsTool, {"query": "nurse"})
    assert "HTTP 429" in str(raised.value)
    assert "Retry after 90 seconds" in str(raised.value)


def test_search_429_with_a_short_retry_after_is_retried_then_succeeds(api):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={}, headers={"Retry-After": "1"})
        return httpx.Response(200, json=SEARCH_RESPONSE)

    mock = api(handler)
    run(SearchJobsTool, {"query": "nurse"})
    assert len(mock.requests) == 2


def test_search_read_timeout_is_not_retried(api):
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    mock = api(slow)
    with pytest.raises(JoboToolError, match="Could not get a response"):
        run(SearchJobsTool, {"query": "nurse"})
    assert len(mock.requests) == 1


def test_missing_key_raises_without_a_request(api):
    mock = api(reply(200, SEARCH_RESPONSE))
    with pytest.raises(JoboToolError, match="API key is required"):
        run(SearchJobsTool, {"query": "x"}, creds={})
    assert mock.requests == []


# -------------------------------------------------------------------- get_job


def test_get_job_request_and_content(api):
    mock = api(reply(200, JOB))
    messages = run(GetJobTool, {"job_id": f"  {JOB_ID.upper()} "})
    assert mock.last.method == "GET"
    assert str(mock.last.url) == f"https://connect.jobo.world/api/jobs/{JOB_ID}"
    assert mock.last.headers["X-Api-Key"] == KEY
    assert "Full employer description." in texts(messages)
    assert json_of(messages)["found"] is True


def test_get_job_can_leave_out_the_description(api):
    api(reply(200, JOB))
    messages = run(GetJobTool, {"job_id": JOB_ID, "include_description": False})
    assert "Full employer description." not in texts(messages)


def test_get_job_rejects_a_non_uuid_without_a_request(api):
    mock = api(reply(200, JOB))
    messages = run(GetJobTool, {"job_id": "../../api/keys"})
    assert "is not a Jobo job id" in texts(messages)
    assert mock.requests == []


def test_get_job_unknown_id_is_a_message(api):
    api(reply(404, {"title": "Job not found"}))
    messages = run(GetJobTool, {"job_id": JOB_ID})
    assert "No job exists" in texts(messages)
    assert json_of(messages)["found"] is False


def test_get_job_other_404_is_an_error(api):
    api(reply(404, {"title": "Not Found"}))
    with pytest.raises(JoboToolError, match="404"):
        run(GetJobTool, {"job_id": JOB_ID})


def test_get_job_401(api):
    api(reply(401, {}))
    with pytest.raises(JoboToolError, match="rejected the API key"):
        run(GetJobTool, {"job_id": JOB_ID})


# -------------------------------------------------------------- find_companies


def test_find_companies_uses_the_free_typeahead_and_clamps_the_limit(api):
    mock = api(
        reply(
            200,
            {
                "suggestions": [
                    {
                        "name": "Stripe",
                        "domain": "stripe.com",
                        "ids": ["id-1", "id-2"],
                        "job_count": 321,
                    }
                ]
            },
        )
    )
    messages = run(FindCompaniesTool, {"query": " strip ", "limit": 500})
    request = mock.last
    assert request.url.path == "/api/connectors/companies/suggest"
    assert dict(request.url.params) == {"q": "strip", "limit": "20"}
    assert request.headers["X-Api-Key"] == KEY
    assert "Stripe" in texts(messages)
    assert json_of(messages)["companies"][0]["domain"] == "stripe.com"


def test_find_companies_sandbox_key_gets_guidance_not_an_error(api):
    api(reply(404, {"code": "not_available_in_sandbox"}))
    messages = run(FindCompaniesTool, {"query": "stripe"}, {"jobo_api_key": "jbe_test_x"})
    assert "Do not call this tool again" in texts(messages)


def test_find_companies_429(api):
    api(reply(429, {}, {"Retry-After": "120"}))
    with pytest.raises(JoboToolError, match="HTTP 429"):
        run(FindCompaniesTool, {"query": "stripe"})


# ---------------------------------------------------------- find_filter_values


def test_find_filter_values_request(api):
    mock = api(reply(200, {"options": [{"key": "Software", "count": 99}]}))
    messages = run(FindFilterValuesTool, {"facet": "Industries", "query": "soft", "limit": 80})
    request = mock.last
    assert request.url.path == "/api/connectors/filter-options/industries"
    assert dict(request.url.params) == {"limit": "50", "q": "soft"}
    assert request.headers["X-Api-Key"] == KEY
    assert "Software" in texts(messages)


def test_find_filter_values_rejects_an_unknown_facet(api):
    mock = api(reply(200, {}))
    with pytest.raises(JoboToolError, match="Unknown facet"):
        run(FindFilterValuesTool, {"facet": "colours"})
    assert mock.requests == []


TAXONOMY = {
    "categories": [
        {
            "name": "Healthcare",
            "subcategories": [
                {
                    "name": "Nursing",
                    "occupations": [
                        {"id": "occ-1", "name": "Registered Nurse"},
                        {"id": "occ-2", "name": "Nurse Practitioner"},
                    ],
                }
            ],
        }
    ]
}


def test_find_occupations_fetches_the_taxonomy_once_across_tool_calls(api):
    # Dify builds a new tool, client and service for every call, as `run` does.
    mock = api(reply(200, TAXONOMY))
    first = run(FindFilterValuesTool, {"facet": "occupations", "query": "nurse"})
    run(FindFilterValuesTool, {"facet": "occupations", "query": "practitioner"})
    assert [r.url.path for r in mock.requests] == ["/api/occupations"]
    assert "occ-1" in texts(first)


def test_find_occupations_cache_is_per_api_key(api):
    mock = api(reply(200, TAXONOMY))
    run(FindFilterValuesTool, {"facet": "occupations", "query": "nurse"})
    run(
        FindFilterValuesTool,
        {"facet": "occupations", "query": "nurse"},
        {"jobo_api_key": "jbe_live_another_key_0000"},
    )
    assert len(mock.requests) == 2
    assert mock.last.headers["X-Api-Key"] == "jbe_live_another_key_0000"


def test_find_occupations_refetches_the_taxonomy_after_the_ttl(api):
    from jobo_client import service as service_module

    mock = api(reply(200, TAXONOMY))
    run(FindFilterValuesTool, {"facet": "occupations", "query": "nurse"})
    for key, (loaded_at, rows) in list(service_module._TAXONOMY_CACHE.items()):
        service_module._TAXONOMY_CACHE[key] = (
            loaded_at - service_module._TAXONOMY_TTL_SECONDS - 1,
            rows,
        )
    run(FindFilterValuesTool, {"facet": "occupations", "query": "nurse"})
    assert len(mock.requests) == 2


def test_find_filter_values_401(api):
    api(reply(401, {}))
    with pytest.raises(JoboToolError, match="rejected the API key"):
        run(FindFilterValuesTool, {"facet": "skills"})


# -------------------------------------------------------------- find_locations


def test_find_locations_uses_the_free_connector_typeahead_not_geocode(api):
    mock = api(
        reply(200, {"suggestions": [{"display_name": "Berlin, Germany"}]})
    )
    messages = run(FindLocationsTool, {"query": "Berl", "limit": 50})
    assert "1. Berlin, Germany" in texts(messages)
    request = mock.last
    assert request.url.path == "/api/connectors/locations/suggest"
    assert "geocode" not in str(request.url)
    assert dict(request.url.params) == {"q": "Berl", "limit": "10"}
    assert request.headers["X-Api-Key"] == KEY


def test_find_locations_sandbox_key_gets_guidance(api):
    api(reply(404, {"code": "not_available_in_sandbox"}))
    messages = run(FindLocationsTool, {"query": "Berlin"}, {"jobo_api_key": "jbe_test_x"})
    assert "Do not call this tool again" in texts(messages)


def test_find_locations_503_with_retry_after_is_retried_then_reported(api):
    mock = api(reply(503, {"title": "Unavailable"}, {"Retry-After": "5"}))
    with pytest.raises(JoboToolError, match="503"):
        run(FindLocationsTool, {"query": "Berlin"})
    assert len(mock.requests) == 3  # one try and two retries


def test_find_locations_500_is_retried_then_reported(api):
    mock = api(reply(500, {"title": "boom"}))
    with pytest.raises(JoboToolError, match="500"):
        run(FindLocationsTool, {"query": "Berlin"})
    assert len(mock.requests) == 3


def test_search_503_without_retry_after_is_not_retried(api):
    # The API's "Search took too long": the same request times out again.
    mock = api(reply(503, {"title": "Search took too long"}))
    with pytest.raises(JoboToolError, match="Search took too long"):
        run(SearchJobsTool, {"query": "nurse"})
    assert len(mock.requests) == 1


def test_search_503_with_retry_after_is_retried_then_succeeds(api):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                503, json={"title": "Search temporarily unavailable"}, headers={"Retry-After": "5"}
            )
        return httpx.Response(200, json=SEARCH_RESPONSE)

    mock = api(handler)
    run(SearchJobsTool, {"query": "nurse"})
    assert len(mock.requests) == 2


# --------------------------------------------------------- list_hiring_signals

COMPANY_ID = "0f8e2a52-3c1d-4b7e-9a10-5d6c7b8a9e01"
SIGNAL = {
    "id": "5b0c1d2e-3f40-4a5b-8c6d-7e8f90a1b2c3",
    "type": "hiring_surge",
    "detected_on": "2026-11-20",
    "created_at": "2026-11-20T06:12:00Z",
    "window_start": "2026-11-14",
    "window_end": "2026-11-20",
    "strength": 82,
    "company": {
        "id": COMPANY_ID,
        "name": "Acme",
        "domain": "acme.com",
        "country_code": "US",
        "size": "201-500",
        "industry": "Software",
        "industries": ["Software"],
        "categories": ["saas"],
        "is_agency": False,
    },
    "details": {"new_jobs": 17, "baseline_weekly_avg": 3.1, "is_agency": False},
    "focus": {"functions": ["technology"], "topics": [], "job_countries": ["US"], "job_regions": [], "job_cities": []},
    "evidence_job_ids": [JOB_ID, "b2c3d4e5-f6a7-8901-bcde-f12345678901"],
}
SIGNALS_RESPONSE = {"signals": [SIGNAL], "has_more": True, "next_cursor": "cur_2"}


def test_signals_request_shape_and_auth_header(api):
    mock = api(reply(200, SIGNALS_RESPONSE, {"X-Credits-Deducted": "30"}))
    run(
        ListHiringSignalsTool,
        {
            "types": "Hiring_Surge, new_country",
            "domains": "stripe.com, acme.com",
            "countries": "us, de",
            "company_sizes": "51-200, 10001+",
            "industries": "Software; Financial Services",
            "funding_stages": "Seed; Series A",
            "functions": "Technology; Sales",
            "roles": "data engineer, nurse",
            "seniority": "Senior, vp",
            "technologies": "Snowflake",
            "skills": "Rust",
            "job_countries": "gb",
            "min_strength": 40.0,
            "detected_after": "2026-11-01",
            "detected_before": "2026-11-20",
            "created_after": "2026-11-12T09:30:00Z",
            "exclude_agencies": True,
            "limit": 3,
            "cursor": "cur_1",
        },
    )
    request = mock.last
    assert request.method == "GET"
    assert request.url.path == "/api/signals"
    assert request.headers["X-Api-Key"] == KEY
    assert request.headers["X-Jobo-Client"] == "dify"
    assert dict(request.url.params) == {
        "types": "hiring_surge,new_country",
        "domains": "stripe.com,acme.com",
        "countries": "US,DE",
        "company_sizes": "51-200,10001+",
        "industries": "Software,Financial Services",
        "funding_stages": "Seed,Series A",
        "functions": "Technology,Sales",
        "roles": "data engineer,nurse",
        "seniority": "senior,vp",
        "technologies": "Snowflake",
        "skills": "Rust",
        "job_countries": "GB",
        "min_strength": "40",
        "detected_after": "2026-11-01",
        "detected_before": "2026-11-20",
        "created_after": "2026-11-12T09:30:00Z",
        "exclude_agencies": "true",
        "limit": "3",
        "cursor": "cur_1",
    }


def test_signals_send_only_what_was_given_and_a_small_default_limit(api):
    mock = api(reply(200, SIGNALS_RESPONSE))
    run(ListHiringSignalsTool, {"domains": "stripe.com", "exclude_agencies": False, "min_strength": 0})
    assert dict(mock.last.url.params) == {"domains": "stripe.com", "limit": "5"}


def test_signals_limit_is_capped_at_25_and_the_cap_is_reported(api):
    mock = api(reply(200, SIGNALS_RESPONSE))
    messages = run(ListHiringSignalsTool, {"domains": "acme.com", "limit": 200})
    assert mock.last.url.params["limit"] == "25"
    assert "limit was capped at 25" in texts(messages)


def test_signals_limit_under_the_cap_is_kept_and_not_reported(api):
    mock = api(reply(200, SIGNALS_RESPONSE))
    messages = run(ListHiringSignalsTool, {"domains": "acme.com", "limit": 10})
    assert mock.last.url.params["limit"] == "10"
    assert "capped" not in texts(messages)


def test_signals_company_mode_uses_the_per_company_endpoint(api):
    mock = api(reply(200, SIGNALS_RESPONSE))
    run(
        ListHiringSignalsTool,
        {
            "company_id": f" {COMPANY_ID.upper()} ",
            "types": "leadership_hire",
            "min_strength": 50,
            "detected_after": "2026-11-01",
            "created_after": "2026-11-12",
            "cursor": "cur_1",
        },
    )
    request = mock.last
    assert request.url.path == f"/api/companies/{COMPANY_ID}/signals"
    assert dict(request.url.params) == {
        "types": "leadership_hire",
        "min_strength": "50",
        "detected_after": "2026-11-01",
        "created_after": "2026-11-12T00:00:00Z",
        "limit": "5",
        "cursor": "cur_1",
    }


def test_signals_company_mode_refuses_the_filters_it_lacks_by_name(api):
    mock = api(reply(200, SIGNALS_RESPONSE))
    with pytest.raises(JoboToolError) as raised:
        run(
            ListHiringSignalsTool,
            {"company_id": COMPANY_ID, "types": "hiring_surge", "domains": "acme.com", "seniority": "vp"},
        )
    message = str(raised.value)
    assert "Remove domains, seniority" in message
    assert "types" not in message.split("Remove")[1]
    assert mock.requests == []


def test_signals_company_mode_refuses_exclude_agencies(api):
    mock = api(reply(200, SIGNALS_RESPONSE))
    with pytest.raises(JoboToolError, match="Remove exclude_agencies"):
        run(ListHiringSignalsTool, {"company_id": COMPANY_ID, "exclude_agencies": True})
    assert mock.requests == []


def test_signals_company_id_must_be_a_uuid(api):
    mock = api(reply(200, SIGNALS_RESPONSE))
    with pytest.raises(JoboToolError, match="is not a Jobo company id"):
        run(ListHiringSignalsTool, {"company_id": "../../api/keys"})
    assert mock.requests == []


@pytest.mark.parametrize(
    "params, fragment",
    [
        ({"types": "surge"}, "Unknown types"),
        ({"seniority": "intern"}, "Unknown seniority"),
        ({"company_sizes": "1-5"}, "Unknown company_sizes"),
        ({"countries": "USA"}, "countries takes two-letter country codes"),
        ({"job_countries": "Germany"}, "job_countries takes two-letter country codes"),
        ({"industries": "Software, Internet"}, '"Software, Internet" cannot be used in industries'),
        ({"functions": "Sales, Marketing"}, "cannot be used in functions"),
        ({"domains": ", ".join(f"d{i}.com" for i in range(101))}, "domains takes at most 100 values"),
        ({"min_strength": 150}, "min_strength must be between 1 and 100"),
        ({"detected_after": "1 Nov 2026"}, "detected_after must be a date in yyyy-MM-dd form"),
        ({"detected_before": "2026-11-01T00:00:00Z"}, "detected_before must be a date in yyyy-MM-dd form"),
        ({"created_after": "last week"}, "created_after must be an ISO 8601"),
        ({"exclude_agencies": "maybe"}, "exclude_agencies must be true or false"),
        ({"limit": "many"}, "limit must be a whole number"),
    ],
)
def test_signals_invalid_arguments_fail_before_any_request(api, params, fragment):
    mock = api(reply(200, SIGNALS_RESPONSE))
    with pytest.raises(JoboToolError, match=re.escape(fragment)):
        run(ListHiringSignalsTool, params)
    assert mock.requests == []


def test_signals_output_text_and_json(api):
    api(reply(200, SIGNALS_RESPONSE, {"X-Credits-Deducted": "30", "X-Credits-Balance": "970"}))
    messages = run(ListHiringSignalsTool, {"domains": "acme.com"})
    text = texts(messages)
    lines = text.splitlines()
    assert lines[0].startswith("1 hiring signal, newest detection day first.")
    assert 'pass cursor "cur_2"' in lines[0]
    assert "1. Acme (acme.com) - Hiring surge" in text
    assert "17 new jobs this week vs 3.1 a week normally" in text
    assert "Detected: 2026-11-20 | Strength: 82 of 100 (Very strong)" in text
    assert f"{JOB_ID}, b2c3d4e5-f6a7-8901-bcde-f12345678901" in text
    assert f"Company ID: {COMPANY_ID}" in text
    assert lines[-1].startswith("Billing: 1 signal returned, each billed at ten times the price of a job")
    data = json_of(messages)
    assert data["summary"] == {
        "count": 1,
        "has_more": True,
        "next_cursor": "cur_2",
        "billed_signals": 1,
        "credits_deducted": 30,
        "credits_balance": 970,
    }
    signal = data["signals"][0]
    assert signal["type_label"] == "Hiring surge"
    assert signal["summary"] == "17 new jobs this week vs 3.1 a week normally"
    assert signal["company"]["domain"] == "acme.com"
    assert signal["details"]["new_jobs"] == 17
    assert KEY not in json.dumps(data) + text


def test_signals_last_page_says_no_more_remain(api):
    api(reply(200, {"signals": [SIGNAL], "has_more": False}))
    messages = run(ListHiringSignalsTool, {"domains": "acme.com"})
    assert "No more remain." in texts(messages)
    assert "next_cursor" not in json_of(messages)["summary"]


def test_signals_an_unknown_type_is_shown_not_refused(api):
    unknown = {**SIGNAL, "type": "remote_shift", "details": {"share": 0.4}}
    api(reply(200, {"signals": [unknown], "has_more": False}))
    messages = run(ListHiringSignalsTool, {"domains": "acme.com"})
    assert "1. Acme (acme.com) - Remote shift" in texts(messages)
    assert json_of(messages)["signals"][0]["type_label"] == "Remote shift"


def test_signals_empty_result_is_a_message_and_free(api):
    api(reply(200, {"signals": [], "has_more": False}))
    messages = run(ListHiringSignalsTool, {"domains": "acme.com"})
    text = texts(messages)
    assert "No hiring signals matched" in text
    assert text.splitlines()[-1] == "Billing: no signals returned, so nothing was billed."
    assert json_of(messages)["signals"] == []


def test_signals_402_is_explained_and_not_retried(api):
    mock = api(
        reply(
            402,
            {
                "code": "insufficient_credits",
                "title": "Payment required",
                "top_up_url": "https://enterprise.jobo.world/credits?topup=1",
            },
        )
    )
    with pytest.raises(JoboToolError) as raised:
        run(ListHiringSignalsTool, {"domains": "acme.com"})
    message = str(raised.value)
    assert "HTTP 402" in message
    assert "ten times the price of a job" in message
    assert "smaller limit" in message
    assert "https://enterprise.jobo.world/credits?topup=1" in message
    assert len(mock.requests) == 1


def test_signals_403_account_key_required(api):
    api(
        reply(
            403,
            {"title": "Account API key required", "code": "account_key_required"},
        )
    )
    with pytest.raises(JoboToolError) as raised:
        run(ListHiringSignalsTool, {"domains": "acme.com"})
    message = str(raised.value)
    assert "account API key" in message
    assert "https://enterprise.jobo.world/api-keys" in message
    assert KEY not in message


def test_signals_other_403_keeps_the_generic_message(api):
    api(reply(403, {"title": "Forbidden"}))
    with pytest.raises(JoboToolError, match="may not use this endpoint"):
        run(ListHiringSignalsTool, {"domains": "acme.com"})


def test_signals_sandbox_key_is_told_not_to_call_again(api):
    mock = api(reply(404, {"code": "not_available_in_sandbox"}))
    with pytest.raises(JoboToolError) as raised:
        run(ListHiringSignalsTool, {"domains": "acme.com"}, {"jobo_api_key": "jbe_test_x"})
    message = str(raised.value)
    assert "not available with a sandbox API key" in message
    assert "Do not call this tool again" in message
    assert len(mock.requests) == 1


def test_signals_429_names_the_rate_limit(api):
    mock = api(reply(429, {"title": "Too many requests"}, {"Retry-After": "90"}))
    with pytest.raises(JoboToolError) as raised:
        run(ListHiringSignalsTool, {"domains": "acme.com"})
    message = str(raised.value)
    assert "HTTP 429" in message
    assert "Retry after 90 seconds" in message
    assert "20 requests a minute" in message
    assert len(mock.requests) == 1  # a 90-second wait is longer than the tool waits


def test_signals_429_with_a_short_retry_after_is_retried(api):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={}, headers={"Retry-After": "1"})
        return httpx.Response(200, json=SIGNALS_RESPONSE)

    mock = api(handler)
    run(ListHiringSignalsTool, {"domains": "acme.com"})
    assert len(mock.requests) == 2


def test_signals_503_with_retry_after_is_retried(api):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"title": "Unavailable"}, headers={"Retry-After": "2"})
        return httpx.Response(200, json=SIGNALS_RESPONSE)

    mock = api(handler)
    run(ListHiringSignalsTool, {"company_id": COMPANY_ID})
    assert len(mock.requests) == 2


@pytest.mark.parametrize("params", [{"domains": "acme.com"}, {"company_id": COMPANY_ID}])
def test_signals_500_is_not_retried_because_it_may_have_been_billed(api, params):
    mock = api(reply(500, {"title": "boom"}))
    with pytest.raises(JoboToolError) as raised:
        run(ListHiringSignalsTool, params)
    assert "not retried" in str(raised.value)
    assert len(mock.requests) == 1


@pytest.mark.parametrize(
    "failure",
    [httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ConnectError],
)
def test_signals_lost_response_is_not_retried(api, failure):
    def lost(request: httpx.Request) -> httpx.Response:
        raise failure("lost", request=request)

    mock = api(lost)
    with pytest.raises(JoboToolError) as raised:
        run(ListHiringSignalsTool, {"domains": "acme.com"})
    assert "Could not get a response" in str(raised.value)
    assert "not retried" in str(raised.value)
    assert len(mock.requests) == 1
