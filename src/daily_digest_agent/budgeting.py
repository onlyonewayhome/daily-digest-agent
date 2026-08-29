from dataclasses import dataclass, field
from datetime import date

from .config import AppConfig, ModelPrice
from .exceptions import (
    DailyRunLimitExceeded,
    MonthlyBudgetExceeded,
    ProviderBudgetExceeded,
    UnknownModelPricingError,
)
from .models import UsageSummary
from .storage.base import StateStore


@dataclass
class BudgetGuard:
    config: AppConfig
    store: StateStore
    local_date: date
    run_calls: dict[str, int] = field(default_factory=dict)

    def check_run(self, force: bool = False) -> None:
        if not force and self.store.get_successful_runs(self.local_date) >= self.config.budget.max_runs_per_day:
            raise DailyRunLimitExceeded("Maximum successful runs for this local date has been reached")
        self._check_monthly(self.store.get_usage(self.local_date))

    def check_request(self, provider: str, model: str, unsafe_override: bool = False) -> None:
        usage = self.store.get_usage(self.local_date)
        settings = self.config.budget.gemini if provider == "google" else self.config.budget.openai
        calls = self.run_calls.get(provider, 0)
        if not unsafe_override and calls >= settings.max_calls_per_run:
            raise ProviderBudgetExceeded(f"{provider} per-run call limit reached")
        if not unsafe_override and usage.provider_calls_today.get(provider, 0) >= settings.max_calls_per_day:
            raise ProviderBudgetExceeded(f"{provider} daily call limit reached")
        if not unsafe_override:
            self._check_monthly(usage)
            prices = self.config.pricing.google if provider == "google" else self.config.pricing.openai
            price = prices.get(model)
            if (price is None or price.input_per_million is None or price.output_per_million is None):
                if not self.config.budget.allow_unknown_pricing:
                    raise UnknownModelPricingError(
                        f"No pricing is configured for provider/model {provider}/{model}. "
                        "Refusing paid request because allow_unknown_pricing is false."
                    )
        self.run_calls[provider] = calls + 1

    def _check_monthly(self, usage: UsageSummary) -> None:
        threshold = self.config.budget.monthly_usd_cap - self.config.budget.monthly_safety_buffer_usd
        if usage.estimated_monthly_cost_usd >= threshold:
            raise MonthlyBudgetExceeded("Configured monthly estimated cost cap safety threshold has been reached")


def estimate_cost(price: ModelPrice | None, input_tokens: int, output_tokens: int) -> float | None:
    if price is None or price.input_per_million is None or price.output_per_million is None:
        return None
    return (input_tokens * price.input_per_million + output_tokens * price.output_per_million) / 1_000_000
