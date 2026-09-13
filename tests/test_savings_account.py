from decimal import Decimal

import pytest

from bank.accounts.savings_account import SavingsAccount
from bank.exceptions import (
    AccountClosedError,
    AccountFrozenError,
    InsufficientFundsError,
    InvalidOperationError,
)


class TestSavingsAccountCreation:
    def test_creates_with_min_balance_and_rate(
        self, savings_account: SavingsAccount
    ):
        assert savings_account.min_balance == Decimal("100")
        assert savings_account.monthly_interest_rate == Decimal("0.02")

    def test_rejects_initial_balance_below_min_balance(self):
        with pytest.raises(InvalidOperationError):
            SavingsAccount(
                owner="Ivan Ivanov",
                initial_balance=Decimal("50"),
                min_balance=Decimal("100"),
            )

    def test_rejects_negative_min_balance(self):
        with pytest.raises(InvalidOperationError):
            SavingsAccount(owner="Ivan Ivanov", min_balance=Decimal("-1"))

    def test_rejects_negative_interest_rate(self):
        with pytest.raises(InvalidOperationError):
            SavingsAccount(
                owner="Ivan Ivanov", monthly_interest_rate=Decimal("-0.01")
            )

    def test_default_min_balance_allows_full_withdrawal(self):
        acc = SavingsAccount(
            owner="Ivan Ivanov", initial_balance=Decimal("100")
        )
        acc.withdraw(Decimal("100"))
        assert acc.balance == Decimal("0")


class TestSavingsAccountWithdraw:
    def test_allows_withdrawal_down_to_min_balance(
        self, savings_account: SavingsAccount
    ):
        savings_account.withdraw(Decimal("900"))
        assert savings_account.balance == Decimal("100")

    def test_rejects_withdrawal_breaching_min_balance(
        self, savings_account: SavingsAccount
    ):
        with pytest.raises(InsufficientFundsError):
            savings_account.withdraw(Decimal("901"))

    def test_rejects_non_positive_amount(
        self, savings_account: SavingsAccount
    ):
        with pytest.raises(InvalidOperationError):
            savings_account.withdraw(Decimal("0"))

    def test_rejects_invalid_amount_type(
        self, savings_account: SavingsAccount
    ):
        with pytest.raises(InvalidOperationError):
            savings_account.withdraw("not-a-number")

    def test_fails_on_frozen_account(self, savings_account: SavingsAccount):
        savings_account.freeze()
        with pytest.raises(AccountFrozenError):
            savings_account.withdraw(Decimal("10"))

    def test_fails_on_closed_account(self, savings_account: SavingsAccount):
        savings_account.close()
        with pytest.raises(AccountClosedError):
            savings_account.withdraw(Decimal("10"))


class TestSavingsAccountInterest:
    def test_apply_monthly_interest_increases_balance(
        self, savings_account: SavingsAccount
    ):
        interest = savings_account.apply_monthly_interest()
        assert interest == Decimal("20.00")
        assert savings_account.balance == Decimal("1020.00")

    def test_apply_monthly_interest_fails_on_frozen_account(
        self, savings_account: SavingsAccount
    ):
        savings_account.freeze()
        with pytest.raises(AccountFrozenError):
            savings_account.apply_monthly_interest()

    def test_apply_monthly_interest_fails_on_closed_account(
        self, savings_account: SavingsAccount
    ):
        savings_account.close()
        with pytest.raises(AccountClosedError):
            savings_account.apply_monthly_interest()

    def test_apply_monthly_interest_is_noop_with_default_rate(self):
        acc = SavingsAccount(
            owner="Ivan Ivanov", initial_balance=Decimal("1000")
        )
        interest = acc.apply_monthly_interest()
        assert interest == Decimal("0")
        assert acc.balance == Decimal("1000")

    def test_apply_monthly_interest_on_zero_balance(self):
        acc = SavingsAccount(
            owner="Ivan Ivanov", monthly_interest_rate=Decimal("0.05")
        )
        interest = acc.apply_monthly_interest()
        assert interest == Decimal("0")
        assert acc.balance == Decimal("0")

    def test_apply_monthly_interest_compounds_on_repeated_calls(
        self, savings_account: SavingsAccount
    ):
        first = savings_account.apply_monthly_interest()
        second = savings_account.apply_monthly_interest()
        assert first == Decimal("20.00")
        assert second == Decimal("20.40")
        assert savings_account.balance == Decimal("1040.40")


class TestSavingsAccountPolymorphism:
    def test_get_account_info_contains_savings_fields(
        self, savings_account: SavingsAccount
    ):
        info = savings_account.get_account_info()
        assert info["min_balance"] == Decimal("100")
        assert info["monthly_interest_rate"] == Decimal("0.02")

    def test_str_contains_min_balance_and_rate(
        self, savings_account: SavingsAccount
    ):
        text = str(savings_account)
        assert "Min balance" in text
        assert "Monthly rate" in text
