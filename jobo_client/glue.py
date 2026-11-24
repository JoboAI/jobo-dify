"""
The thin layer between Dify's tool classes and the Jobo service.

Dify tool parameters arrive as loose values and a tool reports failure by
raising, so this module builds the service from the stored credential and turns
API failures into messages a person or a model can act on.
"""

from typing import Any, Callable, Mapping, NoReturn

from jobo_client.client import JoboClient
from jobo_client.errors import (
    JoboAuthenticationError,
    JoboConnectionError,
    JoboError,
    JoboInsufficientCreditsError,
    JoboNotFoundError,
    JoboPermissionError,
    JoboRateLimitError,
    JoboServerError,
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


def describe_signals_error(error: Exception) -> str:
    """
    A message for a failed hiring signals call. It never contains the API key.

    Signals are billed per signal returned, at ten times the price of a job,
    and the client never replays a signals request whose answer was lost, so
    the messages say what was and was not retried.
    """
    if isinstance(error, JoboInsufficientCreditsError):
        return (
            f"{error} The Jobo account cannot cover these signals (HTTP 402). Hiring "
            "signals are billed per signal returned, at ten times the price of a job: "
            "the plan's included signals are used first, then the wallet. Top up the "
            "wallet or ask for fewer signals with a smaller limit. This is not retried."
        )
    if isinstance(error, JoboPermissionError) and error.code == "account_key_required":
        return (
            f"{error} Hiring signals are charged to an account, so they need an "
            "account API key (HTTP 403). Create one at "
            "https://enterprise.jobo.world/api-keys and paste it into this plugin's "
            "authorization settings."
        )
    if isinstance(error, JoboNotFoundError) and error.not_available_in_sandbox:
        return (
            "Hiring signals are not available with a sandbox API key (jbe_test_...), "
            "which serves job search and job details only. Use a live account API key. "
            "Do not call this tool again with this key."
        )
    if isinstance(error, JoboRateLimitError):
        return (
            f"{error} The Jobo API rate limit for hiring signals was reached (HTTP 429). "
            "Without a subscription it allows 20 requests a minute, 200 an hour and "
            "1,000 a day. Wait before calling again."
        )
    told_to_retry = isinstance(error, JoboServerError) and (
        error.status_code == 503 and error.retry_after is not None
    )
    if isinstance(error, (JoboServerError, JoboConnectionError)) and not told_to_retry:
        return (
            f"{error} It was not retried: the signals may already have been billed, "
            "and reading them again bills them again."
        )
    return describe_error(error)


def raise_tool_error(
    error: Exception, describe: Callable[[Exception], str] = describe_error
) -> NoReturn:
    """Re-raise `error` as a JoboToolError whose message is safe to show."""
    if isinstance(error, (JoboError, ToolInputError)):
        raise JoboToolError(describe(error)) from error
    raise error
