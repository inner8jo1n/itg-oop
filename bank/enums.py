from enum import StrEnum


class AccountStatus(StrEnum):
    """
    Possible lifecycle statuses of a bank account.
    """

    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"


class Currency(StrEnum):
    """
    Currencies supported by bank accounts.
    """

    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"
    KZT = "KZT"
    CNY = "CNY"


class AssetType(StrEnum):
    """
    Virtual asset types available in an investment portfolio.
    """

    STOCKS = "stocks"
    BONDS = "bonds"
    ETF = "etf"


class ClientStatus(StrEnum):
    """
    Possible states of a bank client's authentication access.
    """

    ACTIVE = "active"
    BLOCKED = "blocked"
