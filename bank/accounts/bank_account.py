import uuid
from decimal import Decimal, InvalidOperation

from bank.accounts.abstract_account import AbstractAccount
from bank.enums import Currency
from bank.exceptions import InsufficientFundsError, InvalidOperationError


class BankAccount(AbstractAccount):
    def __init__(
        self,
        owner: str,
        currency: Currency = Currency.RUB,
        account_id: str | None = None,
        initial_balance: Decimal = Decimal("0"),
    ):
        if not owner or not str(owner).strip():
            raise InvalidOperationError("Owner name must not be empty")
        if not isinstance(currency, Currency):
            raise InvalidOperationError(f"Unsupported currency: {currency!r}")

        validated_balance = self._validate_amount(initial_balance, allow_zero=True)
        super().__init__(
            account_id=account_id or self._generate_account_id(),
            owner=owner,
            initial_balance=validated_balance,
        )
        self._currency = currency

    @staticmethod
    def _generate_account_id() -> str:
        return uuid.uuid4().hex[:12].upper()

    @property
    def currency(self) -> Currency:
        return self._currency

    @staticmethod
    def _validate_amount(amount, allow_zero: bool = False) -> Decimal:
        try:
            validated = Decimal(str(amount))
        except (InvalidOperation, TypeError, ValueError) as err:
            raise InvalidOperationError(
                f"Amount must be a number, got {amount!r}"
            ) from err
        if validated < 0 or (validated == 0 and not allow_zero):
            raise InvalidOperationError(
                f"Amount must be positive, got {validated}"
            )
        return validated

    def deposit(self, amount) -> None:
        self._ensure_operable()
        self._balance += self._validate_amount(amount)

    def withdraw(self, amount) -> None:
        self._ensure_operable()
        validated = self._validate_amount(amount)
        if validated > self._balance:
            raise InsufficientFundsError(
                f"Insufficient funds on {self._account_id}: "
                f"balance {self._balance}, requested {validated}"
            )
        self._balance -= validated

    def get_account_info(self) -> dict:
        return {
            "account_id": self._account_id,
            "owner": self._owner,
            "status": self._status.value,
            "balance": self._balance,
            "currency": self._currency.value,
        }

    def __str__(self) -> str:
        last4 = self._account_id[-4:]
        return (
            f"{self.__class__.__name__} | Client: {self._owner} | "
            f"****{last4} | Status: {self._status.value} | "
            f"Balance: {self._balance} {self._currency.value}"
        )
