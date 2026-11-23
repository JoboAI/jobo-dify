"""
The thin layer between Dify's tool classes and the Jobo service.

Dify tool parameters arrive as loose values and a tool reports failure by
raising, so this module builds the service from the stored credential and turns
API failures into messages a person or a model can act on.
"""

from typing import Any, Mapping, NoReturn

from jobo_client.client import JoboClient
from jobo_client.errors import (
    JoboAuthenticationError,
    JoboError,
    JoboInsufficientCreditsError,
    JoboPermissionError,
    JoboRateLimitError,
)
from jobo_client.service import JoboService, ToolInputError

CREDENTIAL_NAME = "jobo_api_key"


class JoboToolError(Exception):
    """A tool call failed. The message is written for the person or model reading it."""


def service_from_credentials(credentials: Mapping[str, Any]) -> JoboService:
    """Build the service from the provider credentials. Raises JoboToolError."""
    try:
        return JoboService(JoboClient(credentials.get(CREDENTIAL_NAME)))
    except ValueError as exc:
        raise JoboToolError(str(exc)) from exc


def describe_error(error: Exception) -> str:
    """A message for a failed call. It never contains the API key."""
    if isinstance(error, JoboAuthenticationError):
        return (
            "The Jobo API rejected the API key (HTTP 401). Check the key in this "
            "plugin's authorization settings, or create a new one in the Jobo dashboard."
        )
    if isinstance(error, JoboInsufficientCreditsError):
        return (
            f"{error} The Jobo account cannot cover this request (HTTP 402). Search "
            "is billed per job returned, and the API checks that included jobs plus "
            "the wallet cover a full page. Top up the wallet or request a smaller "
            "page_size. This is not retried."
        )
    if isinstance(error, JoboRateLimitError):
        return f"{error} The Jobo API rate limit was reached (HTTP 429). Wait and try again."
    if isinstance(error, JoboPermissionError):
        return f"{error} This API key or account may not use this endpoint (HTTP 403)."
    return str(error)


def raise_tool_error(error: Exception) -> NoReturn:
    """Re-raise `error` as a JoboToolError whose message is safe to show."""
    if isinstance(error, (JoboError, ToolInputError)):
        raise JoboToolError(describe_error(error)) from error
    raise error
