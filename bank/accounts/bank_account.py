import uuid
from decimal import Decimal, InvalidOperation
from typing import override

from bank.accounts.abstract_account import AbstractAccount
from bank.enums import Currency
from bank.exceptions import InsufficientFundsError, InvalidOperationError


class BankAccount(AbstractAccount):
    """
    Concrete bank account with amount validation and currency support.
    """

    def __init__(
        self,
        owner: str,
        currency: Currency = Currency.RUB,
        account_id: str | None = None,
        initial_balance: Decimal = Decimal("0"),
    ):
        """
        Create a new bank account, validating owner, currency and balance.

        :param owner: name of the account owner
        :param currency: currency of the account
        :param account_id: account identifier, auto-generated if not given
        :param initial_balance: starting balance of the account
        """
        if not owner or not str(owner).strip():
            raise InvalidOperationError("Owner name must not be empty")
        if not isinstance(currency, Currency):
            raise InvalidOperationError(f"Unsupported currency: {currency!r}")

        normalized_owner = str(owner).strip()
        normalized_account_id = str(account_id).strip() if account_id else ""

        validated_balance = self._validate_amount(
            initial_balance, allow_zero=True
        )
        super().__init__(
            account_id=normalized_account_id or self._generate_account_id(),
            owner=normalized_owner,
            initial_balance=validated_balance,
        )
        self._currency = currency

    @staticmethod
    def _generate_account_id() -> str:
        """
        Generate a short unique account identifier.

        :return: generated account identifier
        """
        return uuid.uuid4().hex[:12].upper()

    @property
    def currency(self) -> Currency:
        """
        Get the account's currency.

        :return: account currency
        """
        return self._currency

    @staticmethod
    def _validate_amount(amount, allow_zero: bool = False) -> Decimal:
        """
        Validate and convert an amount to a positive Decimal.

        :param amount: value to validate
        :param allow_zero: whether a zero amount is allowed
        :return: validated amount as Decimal
        """
        try:
            validated = Decimal(str(amount))
        except (InvalidOperation, TypeError, ValueError) as err:
            raise InvalidOperationError(
                f"Amount must be a number, got {amount!r}"
            ) from err
        if validated.is_nan() or validated.is_infinite():
            raise InvalidOperationError(
                f"Amount must be finite, got {amount!r}"
            )
        if validated < 0 or (validated == 0 and not allow_zero):
            raise InvalidOperationError(
                f"Amount must be positive, got {validated}"
            )
        return validated

    @override
    def deposit(self, amount) -> None:
        """
        Add funds to the account after validating the amount and status.

        :param amount: amount to deposit
        :return: None
        """
        self._ensure_operable()
        self._balance += self._validate_amount(amount)

    @override
    def withdraw(self, amount) -> None:
        """
        Remove funds from the account after validating the amount,
        status and available balance.

        :param amount: amount to withdraw
        :return: None
        """
        self._ensure_operable()
        validated = self._validate_amount(amount)
        if validated > self._balance:
            raise InsufficientFundsError(
                f"Insufficient funds on {self._account_id}: "
                f"balance {self._balance}, requested {validated}"
            )
        self._balance -= validated

    @override
    def get_account_info(self) -> dict:
        """
        Get a summary of the account's data.

        :return: dictionary with account id, owner, status, balance
            and currency
        """
        return {
            "account_id": self._account_id,
            "owner": self._owner,
            "status": self._status.value,
            "balance": self._balance,
            "currency": self._currency.value,
        }

    @override
    def __str__(self) -> str:
        """
        Build a human-readable representation of the account.

        :return: string with account type, owner, masked id, status and balance
        """
        last4 = self._account_id[-4:]
        return (
            f"{self.__class__.__name__} | Client: {self._owner} | "
            f"****{last4} | Status: {self._status.value} | "
            f"Balance: {self._balance} {self._currency.value}"
        )
