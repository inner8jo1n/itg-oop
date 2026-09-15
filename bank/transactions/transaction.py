import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from bank.accounts.bank_account import BankAccount
from bank.enums import Currency, TransactionStatus, TransactionType
from bank.exceptions import InvalidOperationError

_SENDER_REQUIRED_TYPES = (
    TransactionType.WITHDRAWAL,
    TransactionType.TRANSFER,
    TransactionType.EXTERNAL_TRANSFER,
)
_RECEIVER_REQUIRED_TYPES = (
    TransactionType.DEPOSIT,
    TransactionType.TRANSFER,
    TransactionType.EXTERNAL_TRANSFER,
)


class Transaction:
    """
    A single requested banking operation between at most one sender
    and one receiver account, tracked through its processing
    lifecycle with retry and failure bookkeeping.
    """

    def __init__(
        self,
        type: TransactionType,
        amount: Decimal,
        currency: Currency = Currency.RUB,
        sender: BankAccount | None = None,
        receiver: BankAccount | None = None,
        transaction_id: str | None = None,
        priority: int = 0,
        scheduled_at: datetime | None = None,
        created_at: datetime | None = None,
    ):
        """
        Create a transaction, validating its type, amount, currency
        and the sender/receiver accounts required for that type.

        :param type: kind of operation this transaction represents
        :param amount: amount to move, in `currency`
        :param currency: currency the amount is denominated in; must
            equal `sender.currency` when a sender is given, so the
            debit needs no conversion. TransactionProcessor converts
            into the receiver's own currency on credit
        :param sender: account funds are debited from; required for
            WITHDRAWAL, TRANSFER and EXTERNAL_TRANSFER
        :param receiver: account funds are credited to; required for
            DEPOSIT, TRANSFER and EXTERNAL_TRANSFER
        :param transaction_id: identifier, auto-generated if not given
        :param priority: queue priority, higher is processed first
        :param scheduled_at: earliest time the transaction may run;
            if given, the transaction starts out SCHEDULED
        :param created_at: creation timestamp, defaults to now
        """
        if not isinstance(type, TransactionType):
            raise InvalidOperationError(
                f"Unsupported transaction type: {type!r}"
            )
        if not isinstance(currency, Currency):
            raise InvalidOperationError(f"Unsupported currency: {currency!r}")
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise InvalidOperationError(
                f"Priority must be an int, got {priority!r}"
            )

        self._validate_party(type, "sender", sender, _SENDER_REQUIRED_TYPES)
        self._validate_party(
            type, "receiver", receiver, _RECEIVER_REQUIRED_TYPES
        )
        if (
            sender is not None
            and receiver is not None
            and sender.account_id == receiver.account_id
        ):
            raise InvalidOperationError(
                "Sender and receiver must be different accounts"
            )
        if sender is not None and currency != sender.currency:
            raise InvalidOperationError(
                f"Transaction currency {currency.value} does not match "
                f"sender's currency {sender.currency.value}"
            )

        self._transaction_id = (
            str(transaction_id).strip()
            if transaction_id
            else self._generate_transaction_id()
        )
        self._type = type
        self._amount = self._validate_amount(amount)
        self._currency = currency
        self._fee = Decimal("0")
        self._sender = sender
        self._receiver = receiver
        self._failure_reason: str | None = None
        self._created_at = created_at or datetime.now()
        self._scheduled_at = scheduled_at
        self._processed_at: datetime | None = None
        self._priority = priority
        self._attempts = 0
        self._status = (
            TransactionStatus.SCHEDULED
            if scheduled_at is not None
            else TransactionStatus.PENDING
        )

    @staticmethod
    def _generate_transaction_id() -> str:
        """
        Generate a short unique transaction identifier.

        :return: generated transaction identifier
        """
        return uuid.uuid4().hex[:12].upper()

    @staticmethod
    def _validate_party(
        type: TransactionType,
        role: str,
        account: BankAccount | None,
        required_for: tuple[TransactionType, ...],
    ) -> None:
        """
        Check that a sender/receiver account is supplied exactly when
        the transaction type requires it, and is a BankAccount.

        :param type: transaction type being validated
        :param role: "sender" or "receiver", used in error messages
        :param account: the account supplied for that role, if any
        :param required_for: transaction types that require this role
        :return: None
        """
        required = type in required_for
        if required and account is None:
            raise InvalidOperationError(f"{role} is required for {type.value}")
        if not required and account is not None:
            raise InvalidOperationError(
                f"{role} is not allowed for {type.value}"
            )
        if account is not None and not isinstance(account, BankAccount):
            raise InvalidOperationError(
                f"{role} must be a BankAccount, got {account!r}"
            )

    @staticmethod
    def _validate_amount(amount) -> Decimal:
        """
        Validate and convert an amount to a positive Decimal.

        :param amount: value to validate
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
        if validated <= 0:
            raise InvalidOperationError(
                f"Amount must be positive, got {validated}"
            )
        return validated

    @property
    def transaction_id(self) -> str:
        """
        Get the unique transaction identifier.

        :return: transaction identifier
        """
        return self._transaction_id

    @property
    def type(self) -> TransactionType:
        """
        Get the kind of operation this transaction represents.

        :return: transaction type
        """
        return self._type

    @property
    def amount(self) -> Decimal:
        """
        Get the requested amount, in `currency`.

        :return: transaction amount
        """
        return self._amount

    @property
    def currency(self) -> Currency:
        """
        Get the currency the amount is denominated in.

        :return: transaction currency
        """
        return self._currency

    @property
    def fee(self) -> Decimal:
        """
        Get the fee charged for this transaction, set once processed.

        :return: fee amount, in `currency`
        """
        return self._fee

    @property
    def sender(self) -> BankAccount | None:
        """
        Get the account funds are debited from, if any.

        :return: sender account or None
        """
        return self._sender

    @property
    def receiver(self) -> BankAccount | None:
        """
        Get the account funds are credited to, if any.

        :return: receiver account or None
        """
        return self._receiver

    @property
    def status(self) -> TransactionStatus:
        """
        Get the current lifecycle status of the transaction.

        :return: transaction status
        """
        return self._status

    @property
    def failure_reason(self) -> str | None:
        """
        Get the reason the transaction failed, if it has.

        :return: failure reason or None
        """
        return self._failure_reason

    @property
    def created_at(self) -> datetime:
        """
        Get the time the transaction was created.

        :return: creation timestamp
        """
        return self._created_at

    @property
    def scheduled_at(self) -> datetime | None:
        """
        Get the earliest time the transaction may be processed.

        :return: scheduled timestamp or None if not deferred
        """
        return self._scheduled_at

    @property
    def processed_at(self) -> datetime | None:
        """
        Get the time the transaction reached a terminal status.

        :return: processed timestamp or None if not yet finished
        """
        return self._processed_at

    @property
    def priority(self) -> int:
        """
        Get the queue priority; higher values are processed first.

        :return: priority value
        """
        return self._priority

    @property
    def attempts(self) -> int:
        """
        Get the number of processing attempts made so far.

        :return: attempt count
        """
        return self._attempts

    def _set_fee(self, fee: Decimal) -> None:
        """
        Record the fee charged when this transaction was executed.
        Intended to be called by a TransactionProcessor only.

        :param fee: fee amount, in `currency`
        :return: None
        """
        self._fee = fee

    def record_attempt(self) -> None:
        """
        Record that a processing attempt has started.

        :return: None
        """
        self._attempts += 1

    def mark_processing(self) -> None:
        """
        Transition the transaction into PROCESSING.

        :return: None
        """
        if self._status not in (
            TransactionStatus.PENDING,
            TransactionStatus.SCHEDULED,
        ):
            raise InvalidOperationError(
                f"Cannot process transaction {self._transaction_id} "
                f"in status {self._status.value}"
            )
        self._status = TransactionStatus.PROCESSING

    def mark_completed(self, at: datetime | None = None) -> None:
        """
        Transition the transaction into COMPLETED.

        :param at: completion timestamp, defaults to now
        :return: None
        """
        if self._status != TransactionStatus.PROCESSING:
            raise InvalidOperationError(
                f"Cannot complete transaction {self._transaction_id} "
                f"in status {self._status.value}"
            )
        self._status = TransactionStatus.COMPLETED
        self._processed_at = at or datetime.now()

    def mark_failed(self, reason: str, at: datetime | None = None) -> None:
        """
        Transition the transaction into FAILED with a reason.

        :param reason: description of why the transaction failed
        :param at: failure timestamp, defaults to now
        :return: None
        """
        if self._status != TransactionStatus.PROCESSING:
            raise InvalidOperationError(
                f"Cannot fail transaction {self._transaction_id} "
                f"in status {self._status.value}"
            )
        self._status = TransactionStatus.FAILED
        self._failure_reason = reason
        self._processed_at = at or datetime.now()

    def mark_cancelled(self, at: datetime | None = None) -> None:
        """
        Transition the transaction into CANCELLED.

        :param at: cancellation timestamp, defaults to now
        :return: None
        """
        if self._status not in (
            TransactionStatus.PENDING,
            TransactionStatus.SCHEDULED,
        ):
            raise InvalidOperationError(
                f"Cannot cancel transaction {self._transaction_id} "
                f"in status {self._status.value}; only pending or "
                f"scheduled transactions can be cancelled"
            )
        self._status = TransactionStatus.CANCELLED
        self._processed_at = at or datetime.now()

    def get_summary(self) -> dict:
        """
        Get a summary of the transaction's data.

        :return: dictionary with all transaction fields
        """
        return {
            "transaction_id": self._transaction_id,
            "type": self._type.value,
            "amount": self._amount,
            "currency": self._currency.value,
            "fee": self._fee,
            "sender": self._sender.account_id if self._sender else None,
            "receiver": self._receiver.account_id if self._receiver else None,
            "status": self._status.value,
            "failure_reason": self._failure_reason,
            "created_at": self._created_at,
            "scheduled_at": self._scheduled_at,
            "processed_at": self._processed_at,
            "priority": self._priority,
            "attempts": self._attempts,
        }

    def __str__(self) -> str:
        """
        Build a human-readable representation of the transaction.

        :return: string with type, amount, parties, fee and status
        """
        sender_label = (
            f"****{self._sender.account_id[-4:]}"
            if self._sender
            else "EXTERNAL"
        )
        receiver_label = (
            f"****{self._receiver.account_id[-4:]}"
            if self._receiver
            else "EXTERNAL"
        )
        text = (
            f"Transaction {self._transaction_id} | {self._type.value} | "
            f"{self._amount} {self._currency.value} | "
            f"{sender_label} -> {receiver_label} | "
            f"Status: {self._status.value}"
        )
        if self._fee:
            text += f" | Fee: {self._fee}"
        if self._failure_reason:
            text += f" | Reason: {self._failure_reason}"
        return text
