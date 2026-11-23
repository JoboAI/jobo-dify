"""Each tool: request shape, auth header, error mapping, page cap. No network."""

import json
from typing import Any, Dict, List

import httpx
import pytest

from jobo_client.glue import JoboToolError
from tests.conftest import JOB, JOB_ID, KEY, reply
from tools.find_companies import FindCompaniesTool
from tools.find_filter_values import FindFilterValuesTool
from tools.find_locations import FindLocationsTool
from tools.get_job import GetJobTool
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


def test_find_occupations_searches_the_taxonomy_once_and_caches_it(api):
    taxonomy = {
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
    mock = api(reply(200, taxonomy))
    from jobo_client.glue import service_from_credentials

    service = service_from_credentials(CREDS)
    first = service.find_filter_values("occupations", "nurse")
    service.find_filter_values("occupations", "practitioner")
    assert [r.url.path for r in mock.requests] == ["/api/occupations"]
    assert "occ-1" in first.text


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


def test_find_locations_5xx_is_retried_then_reported(api):
    mock = api(reply(503, {"title": "Unavailable"}))
    with pytest.raises(JoboToolError, match="503"):
        run(FindLocationsTool, {"query": "Berlin"})
    assert len(mock.requests) == 3  # one try and two retries
