"""Credential validation: GET /api/connectors/filters, the free endpoint."""

import httpx
import pytest
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from provider.jobo import JoboProvider
from tests.conftest import KEY, reply

CREDS = {"jobo_api_key": KEY}


def test_valid_key_calls_the_free_filters_endpoint_with_the_key(api):
    mock = api(reply(200, {"facets": []}))
    JoboProvider().validate_credentials(CREDS)
    assert len(mock.requests) == 1
    request = mock.last
    assert request.method == "GET"
    assert str(request.url) == "https://connect.jobo.world/api/connectors/filters"
    assert request.headers["X-Api-Key"] == KEY
    assert request.headers["X-Jobo-Client"] == "dify"


def test_401_is_an_invalid_key(api):
    api(reply(401, {"title": "Unauthorized"}))
    with pytest.raises(ToolProviderCredentialValidationError) as raised:
        JoboProvider().validate_credentials(CREDS)
    assert "rejected the API key" in str(raised.value)
    assert KEY not in str(raised.value)


@pytest.mark.parametrize("creds", [{}, {"jobo_api_key": ""}, {"jobo_api_key": "   "}])
def test_missing_key_is_rejected_without_a_request(api, creds):
    mock = api(reply(200, {}))
    with pytest.raises(ToolProviderCredentialValidationError):
        JoboProvider().validate_credentials(creds)
    assert mock.requests == []


def test_a_rate_limit_is_not_reported_as_a_bad_key(api):
    api(reply(429, {"retry_after_seconds": 500}))
    with pytest.raises(ToolProviderCredentialValidationError) as raised:
        JoboProvider().validate_credentials(CREDS)
    assert "rate limit" in str(raised.value)
    assert "rejected the API key" not in str(raised.value)


def test_a_server_error_surfaces_its_status(api):
    api(reply(500, {"title": "boom"}))
    with pytest.raises(ToolProviderCredentialValidationError) as raised:
        JoboProvider().validate_credentials(CREDS)
    assert "500" in str(raised.value)


def test_sandbox_key_is_accepted_when_the_sandbox_lacks_the_endpoint(api):
    api(reply(404, {"code": "not_available_in_sandbox"}))
    JoboProvider().validate_credentials({"jobo_api_key": "jbe_test_abc"})


def test_any_other_404_is_a_failure(api):
    api(reply(404, {"title": "Not Found"}))
    with pytest.raises(ToolProviderCredentialValidationError):
        JoboProvider().validate_credentials(CREDS)


def test_connection_failure_is_reported_without_the_key(api):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    api(refuse)
    with pytest.raises(ToolProviderCredentialValidationError) as raised:
        JoboProvider().validate_credentials(CREDS)
    assert "Could not get a response" in str(raised.value)
    assert KEY not in str(raised.value)
