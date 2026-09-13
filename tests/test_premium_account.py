from decimal import Decimal

import pytest

from bank.accounts.premium_account import PremiumAccount
from bank.exceptions import (
    AccountClosedError,
    AccountFrozenError,
    InsufficientFundsError,
    InvalidOperationError,
)


class TestPremiumAccountCreation:
    def test_creates_with_limits_and_fee(
        self, premium_account: PremiumAccount
    ):
        assert premium_account.withdrawal_limit == Decimal("5000")
        assert premium_account.overdraft_limit == Decimal("500")
        assert premium_account.transaction_fee == Decimal("10")

    def test_rejects_negative_overdraft_limit(self):
        with pytest.raises(InvalidOperationError):
            PremiumAccount(owner="Ivan Ivanov", overdraft_limit=Decimal("-1"))

    def test_rejects_negative_withdrawal_limit(self):
        with pytest.raises(InvalidOperationError):
            PremiumAccount(owner="Ivan Ivanov", withdrawal_limit=Decimal("-1"))

    def test_rejects_negative_transaction_fee(self):
        with pytest.raises(InvalidOperationError):
            PremiumAccount(owner="Ivan Ivanov", transaction_fee=Decimal("-1"))

    def test_default_withdrawal_limit_allows_large_withdrawal(self):
        acc = PremiumAccount(
            owner="Ivan Ivanov", initial_balance=Decimal("999999")
        )
        acc.withdraw(Decimal("999999"))
        assert acc.balance == Decimal("0")

    def test_default_overdraft_limit_blocks_negative_balance(self):
        acc = PremiumAccount(
            owner="Ivan Ivanov", initial_balance=Decimal("100")
        )
        with pytest.raises(InsufficientFundsError):
            acc.withdraw(Decimal("101"))

    def test_default_transaction_fee_charges_nothing(self):
        acc = PremiumAccount(
            owner="Ivan Ivanov", initial_balance=Decimal("100")
        )
        acc.withdraw(Decimal("40"))
        assert acc.balance == Decimal("60")


class TestPremiumAccountWithdraw:
    def test_charges_transaction_fee(self, premium_account: PremiumAccount):
        premium_account.withdraw(Decimal("100"))
        assert premium_account.balance == Decimal("890")

    def test_allows_overdraft_within_limit(
        self, premium_account: PremiumAccount
    ):
        premium_account.withdraw(Decimal("1490"))
        assert premium_account.balance == Decimal("-500")

    def test_rejects_withdrawal_above_limit(
        self, premium_account: PremiumAccount
    ):
        with pytest.raises(InvalidOperationError):
            premium_account.withdraw(Decimal("5001"))

    def test_allows_withdrawal_exactly_at_limit(self):
        acc = PremiumAccount(
            owner="Ivan Ivanov",
            initial_balance=Decimal("10000"),
            withdrawal_limit=Decimal("5000"),
        )
        acc.withdraw(Decimal("5000"))
        assert acc.balance == Decimal("5000")

    def test_fee_is_flat_regardless_of_withdrawal_size(
        self, premium_account: PremiumAccount
    ):
        premium_account.withdraw(Decimal("50"))
        assert premium_account.balance == Decimal("940")
        premium_account.withdraw(Decimal("200"))
        assert premium_account.balance == Decimal("730")

    def test_fee_alone_can_trigger_overdraft_breach(
        self, premium_account: PremiumAccount
    ):
        # 1000 - 1491 = -491, within the -500 overdraft on its own;
        # it is the added 10 fee that pushes it to -501.
        with pytest.raises(InsufficientFundsError):
            premium_account.withdraw(Decimal("1491"))

    def test_rejects_non_positive_amount(
        self, premium_account: PremiumAccount
    ):
        with pytest.raises(InvalidOperationError):
            premium_account.withdraw(Decimal("0"))

    def test_rejects_invalid_amount_type(
        self, premium_account: PremiumAccount
    ):
        with pytest.raises(InvalidOperationError):
            premium_account.withdraw("not-a-number")

    def test_fails_on_frozen_account(self, premium_account: PremiumAccount):
        premium_account.freeze()
        with pytest.raises(AccountFrozenError):
            premium_account.withdraw(Decimal("10"))

    def test_fails_on_closed_account(self, premium_account: PremiumAccount):
        premium_account.close()
        with pytest.raises(AccountClosedError):
            premium_account.withdraw(Decimal("10"))


class TestPremiumAccountPolymorphism:
    def test_get_account_info_contains_premium_fields(
        self, premium_account: PremiumAccount
    ):
        info = premium_account.get_account_info()
        assert info["withdrawal_limit"] == Decimal("5000")
        assert info["overdraft_limit"] == Decimal("500")
        assert info["transaction_fee"] == Decimal("10")

    def test_str_contains_overdraft_and_fee(
        self, premium_account: PremiumAccount
    ):
        text = str(premium_account)
        assert "Overdraft limit" in text
        assert "Fee" in text
