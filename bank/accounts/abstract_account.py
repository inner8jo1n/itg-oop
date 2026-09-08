from abc import ABC, abstractmethod
from decimal import Decimal

from bank.enums import AccountStatus
from bank.exceptions import AccountClosedError, AccountFrozenError


class AbstractAccount(ABC):
    def __init__(self, account_id: str, owner: str, initial_balance: Decimal):
        self._account_id = account_id
        self._owner = owner
        self._balance = initial_balance
        self._status = AccountStatus.ACTIVE

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def balance(self) -> Decimal:
        return self._balance

    @property
    def status(self) -> AccountStatus:
        return self._status

    def _ensure_operable(self) -> None:
        if self._status == AccountStatus.FROZEN:
            raise AccountFrozenError(f"Account {self._account_id} is frozen")
        if self._status == AccountStatus.CLOSED:
            raise AccountClosedError(f"Account {self._account_id} is closed")

    def freeze(self) -> None:
        if self._status == AccountStatus.CLOSED:
            raise AccountClosedError(f"Account {self._account_id} is closed")
        self._status = AccountStatus.FROZEN

    def unfreeze(self) -> None:
        if self._status == AccountStatus.CLOSED:
            raise AccountClosedError(f"Account {self._account_id} is closed")
        self._status = AccountStatus.ACTIVE

    def close(self) -> None:
        self._status = AccountStatus.CLOSED

    @abstractmethod
    def deposit(self, amount) -> None:
        raise NotImplementedError

    @abstractmethod
    def withdraw(self, amount) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_account_info(self) -> dict:
        raise NotImplementedError
