from datetime import date, datetime
from decimal import Decimal

import pytest

from bank.accounts.bank_account import BankAccount
from bank.accounts.investment_account import InvestmentAccount
from bank.accounts.premium_account import PremiumAccount
from bank.accounts.savings_account import SavingsAccount
from bank.bank import Bank
from bank.client import Client
from bank.enums import Currency

DAY_TIME = datetime(2024, 1, 1, 12, 0, 0)
NIGHT_TIME = datetime(2024, 1, 1, 2, 0, 0)


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


@pytest.fixture
def other_account() -> BankAccount:
    return BankAccount(
        owner="Petr Petrov",
        currency=Currency.RUB,
        initial_balance=Decimal("500"),
    )


@pytest.fixture
def usd_account() -> BankAccount:
    return BankAccount(
        owner="Ivan Ivanov",
        currency=Currency.USD,
        initial_balance=Decimal("100"),
    )


@pytest.fixture
def adult_birth_date() -> date:
    today = date.today()
    return today.replace(year=today.year - 25)


@pytest.fixture
def bank() -> Bank:
    return Bank(name="Test Bank", clock=lambda: DAY_TIME)


@pytest.fixture
def client(bank: Bank, adult_birth_date: date) -> Client:
    return bank.add_client(
        full_name="Petr Sidorov",
        birth_date=adult_birth_date,
        phone="+79990000000",
        email="petr@example.com",
        password="secret123",
    )
