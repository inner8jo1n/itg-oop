from decimal import Decimal

import pytest

from bank.accounts.bank_account import BankAccount
from bank.accounts.investment_account import InvestmentAccount
from bank.accounts.premium_account import PremiumAccount
from bank.accounts.savings_account import SavingsAccount
from bank.enums import Currency


@pytest.fixture
def account() -> BankAccount:
    return BankAccount(
        owner="Ivan Ivanov",
        currency=Currency.RUB,
        initial_balance=Decimal("100"),
    )


@pytest.fixture
def savings_account() -> SavingsAccount:
    return SavingsAccount(
        owner="Ivan Ivanov",
        currency=Currency.RUB,
        initial_balance=Decimal("1000"),
        min_balance=Decimal("100"),
        monthly_interest_rate=Decimal("0.02"),
    )


@pytest.fixture
def premium_account() -> PremiumAccount:
    return PremiumAccount(
        owner="Ivan Ivanov",
        currency=Currency.RUB,
        initial_balance=Decimal("1000"),
        withdrawal_limit=Decimal("5000"),
        overdraft_limit=Decimal("500"),
        transaction_fee=Decimal("10"),
    )


@pytest.fixture
def investment_account() -> InvestmentAccount:
    return InvestmentAccount(
        owner="Ivan Ivanov",
        currency=Currency.RUB,
        initial_balance=Decimal("1000"),
    )
