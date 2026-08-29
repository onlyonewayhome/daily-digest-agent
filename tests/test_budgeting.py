from datetime import date

import pytest

from daily_digest_agent.budgeting import BudgetGuard
from daily_digest_agent.config import AppConfig
from daily_digest_agent.exceptions import (
    DailyRunLimitExceeded,
    MonthlyBudgetExceeded,
    ProviderBudgetExceeded,
)
from daily_digest_agent.models import UsageSummary


class Store:
    runs = 0
    usage = UsageSummary()
    def get_successful_runs(self, local_date): return self.runs
    def get_usage(self, local_date): return self.usage


def guard(valid_config):
    return BudgetGuard(AppConfig.model_validate(valid_config), Store(), date(2026, 8, 29))


def test_run_limit_and_force(valid_config):
    value = guard(valid_config)
    value.store.runs = 1
    with pytest.raises(DailyRunLimitExceeded):
        value.check_run()
    value.check_run(force=True)


def test_daily_call_limit(valid_config):
    value = guard(valid_config)
    value.store.usage = UsageSummary(provider_calls_today={"google": 25})
    with pytest.raises(ProviderBudgetExceeded):
        value.check_request("google")


def test_monthly_cost_limit(valid_config):
    value = guard(valid_config)
    value.store.usage = UsageSummary(estimated_monthly_cost_usd=3.0)
    with pytest.raises(MonthlyBudgetExceeded):
        value.check_run()


def test_force_does_not_bypass_provider_caps(valid_config):
    value = guard(valid_config)
    value.store.usage = UsageSummary(provider_calls_today={"openai": 3})
    with pytest.raises(ProviderBudgetExceeded):
        value.check_request("openai")
    value.check_request("openai", unsafe_override=True)
