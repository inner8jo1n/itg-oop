from decimal import Decimal
from typing import override

from bank.accounts.bank_account import BankAccount
from bank.enums import Currency
from bank.exceptions import InsufficientFundsError, InvalidOperationError


class SavingsAccount(BankAccount):
    """
    Bank account that accrues monthly interest and enforces a minimum
    balance that a withdrawal must not breach.
    """

    def __init__(
        self,
        owner: str,
        currency: Currency = Currency.RUB,
        account_id: str | None = None,
        initial_balance: Decimal = Decimal("0"),
        min_balance: Decimal = Decimal("0"),
        monthly_interest_rate: Decimal = Decimal("0"),
    ):
        """
        Create a savings account with a minimum balance and interest.

        :param owner: name of the account owner
        :param currency: currency of the account
        :param account_id: account identifier, auto-generated if not
            given
        :param initial_balance: starting balance of the account
        :param min_balance: balance a withdrawal must not go below
        :param monthly_interest_rate: fraction applied monthly to the
            balance, e.g. 0.02 for 2%
        """
        validated_min_balance = self._validate_amount(
            min_balance, allow_zero=True
        )
        validated_rate = self._validate_amount(
            monthly_interest_rate, allow_zero=True
        )
        super().__init__(
            owner=owner,
            currency=currency,
            account_id=account_id,
            initial_balance=initial_balance,
        )
        if self._balance < validated_min_balance:
            raise InvalidOperationError(
                f"Initial balance {self._balance} is below the "
                f"minimum balance {validated_min_balance}"
            )
        self._min_balance = validated_min_balance
        self._monthly_interest_rate = validated_rate

    @property
    def min_balance(self) -> Decimal:
        """
        Get the minimum balance withdrawals must not go below.

        :return: minimum balance
        """
        return self._min_balance

    @property
    def monthly_interest_rate(self) -> Decimal:
        """
        Get the monthly interest rate applied to the balance.

        :return: monthly interest rate as a fraction
        """
        return self._monthly_interest_rate

    @override
    def withdraw(self, amount) -> None:
        """
        Remove funds without breaching the minimum balance.

        :param amount: amount to withdraw
        :return: None
        """
        self._ensure_operable()
        validated = self._validate_amount(amount)
        if self._balance - validated < self._min_balance:
            raise InsufficientFundsError(
                f"Withdrawal from {self._account_id} would breach "
                f"the minimum balance {self._min_balance}: balance "
                f"{self._balance}, requested {validated}"
            )
        self._balance -= validated
        self._notify_withdrawal(validated)

    def apply_monthly_interest(self) -> Decimal:
        """
        Accrue interest on the current balance at the monthly rate.

        :return: interest amount added to the balance
        """
        self._ensure_operable()
        interest = self._balance * self._monthly_interest_rate
        self._balance += interest
        return interest

    @override
    def get_account_info(self) -> dict:
        """
        Get a summary of the savings account's data.

        :return: base account info plus min balance and monthly
            interest rate
        """
        info = super().get_account_info()
        info.update(
            {
                "min_balance": self._min_balance,
                "monthly_interest_rate": self._monthly_interest_rate,
            }
        )
        return info

    @override
    def __str__(self) -> str:
        """
        Build a human-readable representation of the account.

        :return: base representation with min balance and rate
        """
        return (
            f"{super().__str__()} | Min balance: {self._min_balance} "
            f"| Monthly rate: {self._monthly_interest_rate}"
        )
