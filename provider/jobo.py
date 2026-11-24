from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from jobo_client.client import JoboClient
from jobo_client.errors import (
    JoboAuthenticationError,
    JoboError,
    JoboNotFoundError,
    JoboPermissionError,
)
from jobo_client.glue import CREDENTIAL_NAME, describe_error


class JoboProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        """
        Check the API key against GET /api/connectors/filters.

        That endpoint answers 401 without a valid key and is never billed, so
        validating a key costs nothing. Only an answer about the key (401 or
        403) rejects it. An outage (5xx), a rate limit (429) or a network
        failure says nothing about the key, so the key is saved unverified and
        a tool call reports the real problem later.
        """
        try:
            client = JoboClient(credentials.get(CREDENTIAL_NAME))
        except ValueError:
            raise ToolProviderCredentialValidationError(
                "A Jobo API key is required. Create one in the Jobo dashboard."
            )
        try:
            client.request("GET", "/api/connectors/filters")
        except (JoboAuthenticationError, JoboPermissionError) as error:
            raise ToolProviderCredentialValidationError(describe_error(error))
        except JoboNotFoundError as error:
            # A sandbox key (jbe_test_...) is accepted but the sandbox does not
            # serve this endpoint. Anything else that is a 404 is a real fault.
            if not error.not_available_in_sandbox:
                raise ToolProviderCredentialValidationError(str(error))
        except JoboError:
            # Could not verify the key either way: accept it.
            return
