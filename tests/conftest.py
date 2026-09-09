from decimal import Decimal

import pytest

from bank.accounts.bank_account import BankAccount
from bank.enums import Currency


@pytest.fixture
def account() -> BankAccount:
    return BankAccount(owner="Ivan Ivanov", currency=Currency.RUB, initial_balance=Decimal("100"))
