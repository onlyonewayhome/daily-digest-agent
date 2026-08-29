import pytest

from daily_digest_agent.exceptions import ProviderOutputError
from daily_digest_agent.retry import is_retryable_error


class HttpError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_statuses_are_retryable(status):
    assert is_retryable_error("google", HttpError(status))


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_permanent_statuses_are_not_retryable(status):
    assert not is_retryable_error("openai", HttpError(status))


def test_validation_errors_are_not_retryable():
    assert not is_retryable_error("google", ProviderOutputError("bad payload"))