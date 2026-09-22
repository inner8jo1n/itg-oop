from abc import ABC, abstractmethod
from collections.abc import Callable
from decimal import Decimal

from bank.enums import AccountStatus
from bank.exceptions import AccountClosedError, AccountFrozenError

_BeforeWithdrawHook = Callable[[Decimal, object | None], None]


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
        self._before_operation: Callable[[], None] | None = None
        self._before_withdraw: _BeforeWithdrawHook | None = None
        self._after_withdraw: Callable[[Decimal], None] | None = None
        self._before_withdraw_assessed_by: object | None = None

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

    def _bind_bank_hooks(
        self,
        before_operation: Callable[[], None],
        after_withdraw: Callable[[Decimal], None],
        before_withdraw: _BeforeWithdrawHook | None = None,
    ) -> None:
        """
        Attach the bank-level checks that every mutating operation on
        this account must pass, regardless of whether it is invoked
        through the bank or directly on the account.

        :param before_operation: called before each operation; raises
            if the operation is not currently allowed
        :param after_withdraw: called with the amount debited after
            each successful withdrawal, to flag suspicious activity
        :param before_withdraw: called with the requested (not yet
            validated) amount and an opaque "assessed_by" token (see
            _mark_before_withdraw_assessed_by) before a withdrawal
            changes the balance; may raise to block the withdrawal
            entirely, e.g. based on risk analysis
        :return: None
        """
        self._before_operation = before_operation
        self._after_withdraw = after_withdraw
        self._before_withdraw = before_withdraw

    def _notify_before_withdraw(self, amount) -> None:
        """
        Give the bound bank hook a chance to block a withdrawal
        before any balance change, regardless of whether withdraw()
        was called through the bank or directly on this account. The
        hook itself decides whether the current assessed_by token (see
        _mark_before_withdraw_assessed_by) means it can trust an
        assessment already done elsewhere - this method never
        silences the hook on its own.

        :param amount: amount about to be withdrawn, unvalidated
        :return: None
        """
        if self._before_withdraw is not None:
            self._before_withdraw(amount, self._before_withdraw_assessed_by)

    def _mark_before_withdraw_assessed_by(
        self, risk_analyzer: object
    ) -> "_AssessedByMarker":
        """
        Context manager that tags this account's next before_withdraw
        call as already assessed by `risk_analyzer`. Intended for a
        caller - such as TransactionProcessor - that already performed
        its own risk assessment for the withdrawal about to happen.

        This does NOT unconditionally silence the bank's hook: it only
        passes `risk_analyzer`'s identity through to it. The bound
        hook (see Bank._check_withdrawal_risk) treats this as
        sufficient only when its own risk_analyzer IS that exact same
        instance - otherwise it still runs its own check in full, so
        a caller configured with a different (or no) analyzer can
        never silently bypass the bank's own risk policy. Always
        restores the previous token on exit, including when the
        withdrawal raises.

        :param risk_analyzer: the analyzer instance that already
            assessed this withdrawal
        :return: context manager applying the assessed_by token
        """
        return _AssessedByMarker(self, risk_analyzer)

    def _ensure_operable(self) -> None:
        """
        Check that the operation is currently allowed and that the
        account is neither frozen nor closed.

        :return: None
        """
        if self._before_operation is not None:
            self._before_operation()
        if self._status == AccountStatus.FROZEN:
            raise AccountFrozenError(f"Account {self._account_id} is frozen")
        if self._status == AccountStatus.CLOSED:
            raise AccountClosedError(f"Account {self._account_id} is closed")

    def _notify_withdrawal(self, withdrawn: Decimal) -> None:
        """
        Report a completed withdrawal to the bound bank hook, if any.

        :param withdrawn: actual amount debited from the balance
        :return: None
        """
        if self._after_withdraw is not None:
            self._after_withdraw(withdrawn)

    def freeze(self) -> None:
        """
        Freeze the account, blocking further operations until unfrozen.

        :return: None
        """
        if self._before_operation is not None:
            self._before_operation()
        if self._status == AccountStatus.CLOSED:
            raise AccountClosedError(f"Account {self._account_id} is closed")
        self._status = AccountStatus.FROZEN

    def unfreeze(self) -> None:
        """
        Unfreeze the account, restoring it to active status.

        :return: None
        """
        if self._before_operation is not None:
            self._before_operation()
        if self._status == AccountStatus.CLOSED:
            raise AccountClosedError(f"Account {self._account_id} is closed")
        self._status = AccountStatus.ACTIVE

    def close(self) -> None:
        """
        Close the account permanently.

        :return: None
        """
        if self._before_operation is not None:
            self._before_operation()
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


class _AssessedByMarker:
    """
    Context manager backing
    AbstractAccount._mark_before_withdraw_assessed_by.
    """

    def __init__(self, account: AbstractAccount, risk_analyzer: object):
        self._account = account
        self._risk_analyzer = risk_analyzer
        self._previous: object | None = None

    def __enter__(self) -> None:
        self._previous = self._account._before_withdraw_assessed_by
        self._account._before_withdraw_assessed_by = self._risk_analyzer

    def __exit__(self, *exc_info) -> None:
        self._account._before_withdraw_assessed_by = self._previous
