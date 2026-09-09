from decimal import Decimal

import pytest

from bank.accounts.bank_account import BankAccount
from bank.enums import AccountStatus, Currency
from bank.exceptions import (
    AccountClosedError,
    AccountFrozenError,
    InsufficientFundsError,
    InvalidOperationError,
)


class TestBankAccountCreation:
    def test_creates_account_with_defaults(self):
        acc = BankAccount(owner="Ivan Ivanov")
        assert acc.owner == "Ivan Ivanov"
        assert acc.currency == Currency.RUB
        assert acc.balance == Decimal("0")
        assert acc.status == AccountStatus.ACTIVE
        assert acc.account_id

    def test_creates_account_with_initial_balance(self):
        acc = BankAccount(owner="Ivan Ivanov", initial_balance=Decimal("500"))
        assert acc.balance == Decimal("500")

    def test_rejects_empty_owner(self):
        with pytest.raises(InvalidOperationError):
            BankAccount(owner="   ")

    def test_rejects_invalid_currency(self):
        with pytest.raises(InvalidOperationError):
            BankAccount(owner="Ivan Ivanov", currency="USD")

    def test_rejects_negative_initial_balance(self):
        with pytest.raises(InvalidOperationError):
            BankAccount(owner="Ivan Ivanov", initial_balance=Decimal("-1"))


class TestDeposit:
    def test_increases_balance(self, account: BankAccount):
        account.deposit(Decimal("50"))
        assert account.balance == Decimal("150")

    def test_rejects_non_positive_amount(self, account: BankAccount):
        with pytest.raises(InvalidOperationError):
            account.deposit(Decimal("0"))

    def test_rejects_invalid_amount_type(self, account: BankAccount):
        with pytest.raises(InvalidOperationError):
            account.deposit("not-a-number")

    def test_fails_on_frozen_account(self, account: BankAccount):
        account.freeze()
        with pytest.raises(AccountFrozenError):
            account.deposit(Decimal("10"))

    def test_fails_on_closed_account(self, account: BankAccount):
        account.close()
        with pytest.raises(AccountClosedError):
            account.deposit(Decimal("10"))


class TestWithdraw:
    def test_decreases_balance(self, account: BankAccount):
        account.withdraw(Decimal("30"))
        assert account.balance == Decimal("70")

    def test_rejects_amount_greater_than_balance(self, account: BankAccount):
        with pytest.raises(InsufficientFundsError):
            account.withdraw(Decimal("1000"))

    def test_rejects_non_positive_amount(self, account: BankAccount):
        with pytest.raises(InvalidOperationError):
            account.withdraw(Decimal("-5"))

    def test_fails_on_frozen_account(self, account: BankAccount):
        account.freeze()
        with pytest.raises(AccountFrozenError):
            account.withdraw(Decimal("10"))

    def test_fails_on_closed_account(self, account: BankAccount):
        account.close()
        with pytest.raises(AccountClosedError):
            account.withdraw(Decimal("10"))


class TestAccountLifecycle:
    def test_freeze_and_unfreeze(self, account: BankAccount):
        account.freeze()
        assert account.status == AccountStatus.FROZEN
        account.unfreeze()
        assert account.status == AccountStatus.ACTIVE

    def test_close_is_terminal(self, account: BankAccount):
        account.close()
        assert account.status == AccountStatus.CLOSED
        with pytest.raises(AccountClosedError):
            account.freeze()
        with pytest.raises(AccountClosedError):
            account.unfreeze()


class TestAccountInfo:
    def test_get_account_info_contains_expected_fields(self, account: BankAccount):
        info = account.get_account_info()
        assert info == {
            "account_id": account.account_id,
            "owner": account.owner,
            "status": AccountStatus.ACTIVE.value,
            "balance": Decimal("100"),
            "currency": Currency.RUB.value,
        }

    def test_str_masks_account_id(self, account: BankAccount):
        text = str(account)
        assert account.account_id[-4:] in text
        assert account.account_id[:-4] not in text
