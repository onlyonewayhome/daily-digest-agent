class DailyDigestError(Exception):
    """Base exception for expected application failures."""


class ConfigurationError(DailyDigestError):
    pass


class BudgetExceeded(DailyDigestError):
    pass


class DailyRunLimitExceeded(BudgetExceeded):
    pass


class ProviderBudgetExceeded(BudgetExceeded):
    pass


class MonthlyBudgetExceeded(BudgetExceeded):
    pass


class UnknownModelPricingError(BudgetExceeded):
    pass


class DuplicateDigestError(DailyDigestError):
    pass


class DiscoveryHealthError(DailyDigestError):
    pass


class ProviderOutputError(DailyDigestError):
    pass
