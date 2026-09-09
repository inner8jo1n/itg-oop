from abc import ABC, abstractmethod
from decimal import Decimal

from bank.enums import AccountStatus
from bank.exceptions import AccountClosedError, AccountFrozenError


class AbstractAccount(ABC):
    """
    Abstract base class for all bank account types.
    """

    def __init__(self, account_id: str, owner: str, initial_balance: Decimal):
        """
        Initialize the account with an id, owner and starting balance.

        :param account_id: unique account identifier
        :param owner: name of the account owner
        :param initial_balance: starting balance of the account
        """
        self._account_id = account_id
        self._owner = owner
        self._balance = initial_balance
        self._status = AccountStatus.ACTIVE

    @property
    def account_id(self) -> str:
        """
        Get the unique account identifier.

        :return: account identifier
        """
        return self._account_id

    @property
    def owner(self) -> str:
        """
        Get the account owner's name.

        :return: owner name
        """
        return self._owner

    @property
    def balance(self) -> Decimal:
        """
        Get the current account balance.

        :return: current balance
        """
        return self._balance

    @property
    def status(self) -> AccountStatus:
        """
        Get the current account status.

        :return: current account status
        """
        return self._status

    def _ensure_operable(self) -> None:
        """
        Check that the account is neither frozen nor closed.

        :return: None
        """
        if self._status == AccountStatus.FROZEN:
            raise AccountFrozenError(f"Account {self._account_id} is frozen")
        if self._status == AccountStatus.CLOSED:
            raise AccountClosedError(f"Account {self._account_id} is closed")

    def freeze(self) -> None:
        """
        Freeze the account, blocking further operations until unfrozen.

        :return: None
        """
        if self._status == AccountStatus.CLOSED:
            raise AccountClosedError(f"Account {self._account_id} is closed")
        self._status = AccountStatus.FROZEN

    def unfreeze(self) -> None:
        """
        Unfreeze the account, restoring it to active status.

        :return: None
        """
        if self._status == AccountStatus.CLOSED:
            raise AccountClosedError(f"Account {self._account_id} is closed")
        self._status = AccountStatus.ACTIVE

    def close(self) -> None:
        """
        Close the account permanently.

        :return: None
        """
        self._status = AccountStatus.CLOSED

    @abstractmethod
    def deposit(self, amount) -> None:
        """
        Add funds to the account.

        :param amount: amount to deposit
        :return: None
        """
        raise NotImplementedError

    @abstractmethod
    def withdraw(self, amount) -> None:
        """
        Remove funds from the account.

        :param amount: amount to withdraw
        :return: None
        """
        raise NotImplementedError

    @abstractmethod
    def get_account_info(self) -> dict:
        """
        Get a summary of the account's data.

        :return: dictionary with account information
        """
        raise NotImplementedError
