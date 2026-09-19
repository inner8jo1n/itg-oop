from decimal import Decimal
from typing import override

from bank.accounts.bank_account import BankAccount
from bank.enums import Currency
from bank.exceptions import InsufficientFundsError, InvalidOperationError


class PremiumAccount(BankAccount):
    """
    Bank account with an elevated per-withdrawal limit, an overdraft
    allowance and a fixed fee charged on each withdrawal.
    """

    def __init__(
        self,
        owner: str,
        currency: Currency = Currency.RUB,
        account_id: str | None = None,
        initial_balance: Decimal = Decimal("0"),
        withdrawal_limit: Decimal = Decimal("1000000"),
        overdraft_limit: Decimal = Decimal("0"),
        transaction_fee: Decimal = Decimal("0"),
    ):
        """
        Create a premium account with elevated limits and overdraft.

        :param owner: name of the account owner
        :param currency: currency of the account
        :param account_id: account identifier, auto-generated if not
            given
        :param initial_balance: starting balance of the account
        :param withdrawal_limit: maximum amount allowed per withdrawal
        :param overdraft_limit: amount the balance may go negative by
        :param transaction_fee: fixed fee charged on each withdrawal
        """
        super().__init__(
            owner=owner,
            currency=currency,
            account_id=account_id,
            initial_balance=initial_balance,
        )
        self._withdrawal_limit = self._validate_amount(
            withdrawal_limit, allow_zero=True
        )
        self._overdraft_limit = self._validate_amount(
            overdraft_limit, allow_zero=True
        )
        self._transaction_fee = self._validate_amount(
            transaction_fee, allow_zero=True
        )

    @property
    def withdrawal_limit(self) -> Decimal:
        """
        Get the maximum amount allowed per withdrawal.

        :return: withdrawal limit
        """
        return self._withdrawal_limit

    @property
    def overdraft_limit(self) -> Decimal:
        """
        Get the amount the balance is allowed to go negative by.

        :return: overdraft limit
        """
        return self._overdraft_limit

    @property
    def transaction_fee(self) -> Decimal:
        """
        Get the fixed fee charged on each withdrawal.

        :return: transaction fee
        """
        return self._transaction_fee

    @override
    def withdraw(self, amount) -> None:
        """
        Remove funds and a fixed fee, allowing the balance to go
        negative up to the overdraft limit.

        :param amount: amount to withdraw
        :return: None
        """
        self._ensure_operable()
        self._notify_before_withdraw(amount)
        validated = self._validate_amount(amount)
        if validated > self._withdrawal_limit:
            raise InvalidOperationError(
                f"Withdrawal {validated} exceeds the limit "
                f"{self._withdrawal_limit} on {self._account_id}"
            )
        total_debit = validated + self._transaction_fee
        if self._balance - total_debit < -self._overdraft_limit:
            raise InsufficientFundsError(
                f"Insufficient funds on {self._account_id}: balance "
                f"{self._balance}, requested {validated} plus fee "
                f"{self._transaction_fee}, overdraft limit "
                f"{self._overdraft_limit}"
            )
        self._balance -= total_debit
        self._notify_withdrawal(total_debit)

    @override
    def get_account_info(self) -> dict:
        """
        Get a summary of the premium account's data.

        :return: base account info plus withdrawal limit, overdraft
            limit and transaction fee
        """
        info = super().get_account_info()
        info.update(
            {
                "withdrawal_limit": self._withdrawal_limit,
                "overdraft_limit": self._overdraft_limit,
                "transaction_fee": self._transaction_fee,
            }
        )
        return info

    @override
    def __str__(self) -> str:
        """
        Build a human-readable representation of the account.

        :return: base representation with overdraft limit and fee
        """
        return (
            f"{super().__str__()} | Overdraft limit: "
            f"{self._overdraft_limit} | Fee: {self._transaction_fee}"
        )
