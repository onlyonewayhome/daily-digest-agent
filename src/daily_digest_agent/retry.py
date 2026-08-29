from __future__ import annotations

from .exceptions import BudgetExceeded, ConfigurationError, ProviderOutputError

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _status_code(exc: Exception) -> int | None:
    for value in (getattr(exc, "status_code", None), getattr(exc, "code", None)):
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def is_retryable_error(provider: str, exc: Exception) -> bool:
    if isinstance(exc, (BudgetExceeded, ConfigurationError, ProviderOutputError, ValueError, TypeError)):
        return False
    status = _status_code(exc)
    if status is not None:
        return status in RETRYABLE_STATUS_CODES
    name = type(exc).__name__.lower()
    if provider == "google":
        return any(marker in name for marker in ("resourceexhausted", "serviceunavailable", "internalservererror"))
    if provider == "openai":
        return any(marker in name for marker in ("ratelimiterror", "apiconnectionerror", "internalsystemerror"))
    return False