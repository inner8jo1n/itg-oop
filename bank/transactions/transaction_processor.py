import logging
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from bank.accounts.bank_account import BankAccount
from bank.enums import Currency, TransactionStatus, TransactionType
from bank.exceptions import (
    BankError,
    ExchangeRateNotFoundError,
    InvalidOperationError,
    OperationNotAllowedError,
)
from bank.transactions.transaction import Transaction
from bank.transactions.transaction_queue import TransactionQueue

logger = logging.getLogger(__name__)

_Handler = Callable[[Transaction], None]


class TransactionProcessor:
    """
    Executes transactions against their sender/receiver accounts,
    applying currency conversion and external-transfer fees.

    Frozen/closed accounts and transfers that would take a
    non-premium account below zero are rejected by the accounts'
    own `deposit`/`withdraw` methods, which this processor relies
    on polymorphically rather than re-implementing those rules.
    """

    def __init__(
        self,
        exchange_rates: dict[tuple[Currency, Currency], Decimal] | None = None,
        external_transfer_fee_rate: Decimal = Decimal("0.01"),
        max_retries: int = 3,
        retryable_errors: tuple[type[BankError], ...] = (
            OperationNotAllowedError,
        ),
        clock: Callable[[], datetime] = datetime.now,
    ):
        """
        Create a transaction processor.

        :param exchange_rates: mapping of (from, to) currency pairs
            to conversion rates; same-currency conversions never
            need an entry
        :param external_transfer_fee_rate: fraction of the amount
            charged as a fee on EXTERNAL_TRANSFER transactions
        :param max_retries: maximum processing attempts per
            transaction before it is marked failed
        :param retryable_errors: exception types that trigger a
            retry instead of immediately failing the transaction
        :param clock: callable returning the current datetime, used
            to stamp completion/failure times
        """
        if not isinstance(max_retries, int) or max_retries < 1:
            raise InvalidOperationError(
                f"max_retries must be a positive int, got {max_retries!r}"
            )
        if external_transfer_fee_rate < 0:
            raise InvalidOperationError(
                "external_transfer_fee_rate must not be negative, got "
                f"{external_transfer_fee_rate!r}"
            )
        for pair, rate in (exchange_rates or {}).items():
            if rate <= 0:
                raise InvalidOperationError(
                    f"Exchange rate for {pair} must be positive, got {rate!r}"
                )
        self._exchange_rates = dict(exchange_rates or {})
        self._external_transfer_fee_rate = external_transfer_fee_rate
        self._max_retries = max_retries
        self._retryable_errors = retryable_errors
        self._clock = clock
        self._handlers: dict[TransactionType, _Handler] = {
            TransactionType.DEPOSIT: self._execute_deposit,
            TransactionType.WITHDRAWAL: self._execute_withdrawal,
            TransactionType.TRANSFER: self._execute_transfer,
            TransactionType.EXTERNAL_TRANSFER: self._execute_external_transfer,
        }

    def convert(
        self, amount: Decimal, from_currency: Currency, to_currency: Currency
    ) -> Decimal:
        """
        Convert an amount between currencies using the configured
        exchange rates.

        :param amount: amount to convert, in `from_currency`
        :param from_currency: currency the amount is denominated in
        :param to_currency: currency to convert into
        :return: converted amount, in `to_currency`
        """
        if from_currency == to_currency:
            return amount
        rate = self._exchange_rates.get((from_currency, to_currency))
        if rate is None:
            raise ExchangeRateNotFoundError(
                f"No exchange rate from {from_currency.value} to "
                f"{to_currency.value}"
            )
        return amount * rate

    def _execute_deposit(self, transaction: Transaction) -> None:
        """
        Credit the receiver with the transaction amount, converted
        into the receiver's currency. No fee applies.

        :param transaction: DEPOSIT transaction to execute
        :return: None
        """
        receiver = transaction.receiver
        credited = self.convert(
            transaction.amount, transaction.currency, receiver.currency
        )
        receiver.deposit(credited)
        transaction._set_fee(Decimal("0"))

    def _execute_withdrawal(self, transaction: Transaction) -> None:
        """
        Debit the sender by the transaction amount. This processor
        charges no fee of its own for a withdrawal, but the recorded
        fee reflects whatever the account actually debited beyond
        the requested amount (e.g. PremiumAccount's own fixed
        transaction fee), measured from the actual balance change
        rather than assumed to be zero.

        :param transaction: WITHDRAWAL transaction to execute
        :return: None
        """
        sender = transaction.sender
        balance_before = sender.balance
        sender.withdraw(transaction.amount)
        actual_debited = balance_before - sender.balance
        transaction._set_fee(actual_debited - transaction.amount)

    def _execute_transfer(self, transaction: Transaction) -> None:
        """
        Move funds between sender and receiver. This processor
        charges no fee of its own for an internal transfer, though
        the sender's account may still charge one (see _move_funds).

        :param transaction: TRANSFER transaction to execute
        :return: None
        """
        self._move_funds(transaction, processor_fee=Decimal("0"))

    def _execute_external_transfer(self, transaction: Transaction) -> None:
        """
        Move funds between sender and receiver, charging the
        configured external-transfer fee on top of the amount.

        :param transaction: EXTERNAL_TRANSFER transaction to execute
        :return: None
        """
        processor_fee = transaction.amount * self._external_transfer_fee_rate
        self._move_funds(transaction, processor_fee=processor_fee)

    def _move_funds(
        self, transaction: Transaction, processor_fee: Decimal
    ) -> None:
        """
        Debit the sender for the amount plus this processor's own
        fee (both in the transaction's currency) and credit the
        receiver with the amount converted into the receiver's
        currency. The fee recorded on `transaction` is measured from
        the sender's actual balance change rather than assumed to
        equal `processor_fee`, since some account types (e.g.
        PremiumAccount) silently deduct an additional fee of their
        own on top of what withdraw() was asked for. If the
        receiver's deposit fails after the sender was already
        debited, the debit is refunded so no funds are destroyed.

        :param transaction: transaction being executed
        :param processor_fee: fee this processor adds to the
            sender's debit, in the transaction's currency; the
            account itself may add more on top
        :return: None
        """
        sender = transaction.sender
        receiver = transaction.receiver
        debit_amount = transaction.amount + processor_fee
        credited = self.convert(
            transaction.amount, transaction.currency, receiver.currency
        )
        balance_before = sender.balance
        sender.withdraw(debit_amount)
        actual_debited = balance_before - sender.balance
        try:
            receiver.deposit(credited)
        except BankError as deposit_error:
            self._refund_or_raise(
                transaction, sender, actual_debited, deposit_error
            )
        transaction._set_fee(actual_debited - transaction.amount)

    @staticmethod
    def _refund_or_raise(
        transaction: Transaction,
        sender: BankAccount,
        actual_debited: Decimal,
        deposit_error: BankError,
    ) -> None:
        """
        Refund a sender debit after the matching receiver deposit
        failed. If the refund itself fails, funds are genuinely
        unaccounted for: log it as critical and raise a non-retryable
        error so the caller never retries and debits the sender
        again.

        :param transaction: transaction being executed
        :param sender: account that was already debited
        :param actual_debited: the amount actually removed from the
            sender's balance, to refund back to the sender
        :param deposit_error: the original error from the receiver's
            deposit, always re-raised when the refund succeeds
        :return: None
        """
        try:
            sender.deposit(actual_debited)
        except BankError as refund_error:
            logger.critical(
                "transaction %s: refund of %s to sender %s failed "
                "after receiver deposit failed; funds are "
                "unaccounted for. Deposit error: %s. Refund error: %s",
                transaction.transaction_id,
                actual_debited,
                sender.account_id,
                deposit_error,
                refund_error,
            )
            raise InvalidOperationError(
                f"Refund to {sender.account_id} failed after "
                f"deposit to receiver failed: {refund_error}"
            ) from deposit_error
        raise deposit_error

    def process(self, transaction: Transaction) -> None:
        """
        Process a single transaction, retrying on transient errors
        up to the configured limit before marking it failed.

        :param transaction: transaction to process; must be PENDING,
            or SCHEDULED with `scheduled_at` already due
        :return: None
        """
        if not isinstance(transaction, Transaction):
            raise InvalidOperationError(
                f"Expected a Transaction, got {transaction!r}"
            )
        if (
            transaction.status == TransactionStatus.SCHEDULED
            and transaction.scheduled_at is not None
            and transaction.scheduled_at > self._clock()
        ):
            raise InvalidOperationError(
                f"Transaction {transaction.transaction_id} is "
                f"scheduled for {transaction.scheduled_at}, which "
                f"has not yet arrived"
            )
        transaction.mark_processing()
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            transaction.record_attempt()
            try:
                self._handlers[transaction.type](transaction)
            except self._retryable_errors as err:
                last_error = err
                logger.warning(
                    "transaction %s attempt %d/%d failed (retryable): %s",
                    transaction.transaction_id,
                    attempt,
                    self._max_retries,
                    err,
                )
                continue
            except BankError as err:
                logger.error(
                    "transaction %s failed: %s",
                    transaction.transaction_id,
                    err,
                )
                transaction.mark_failed(str(err), at=self._clock())
                return
            else:
                logger.info(
                    "transaction %s completed on attempt %d/%d",
                    transaction.transaction_id,
                    attempt,
                    self._max_retries,
                )
                transaction.mark_completed(at=self._clock())
                return
        logger.error(
            "transaction %s exhausted %d attempts, last error: %s",
            transaction.transaction_id,
            self._max_retries,
            last_error,
        )
        transaction.mark_failed(
            f"Failed after {self._max_retries} attempts: {last_error}",
            at=self._clock(),
        )

    def process_queue(
        self, queue: TransactionQueue, limit: int | None = None
    ) -> list[Transaction]:
        """
        Process ready transactions from a queue, in priority order,
        until it has no more ready transactions or `limit` is hit.

        :param queue: queue to pop and process transactions from
        :param limit: maximum number of transactions to process
        :return: list of processed transactions, in the order they
            were processed
        """
        processed: list[Transaction] = []
        while limit is None or len(processed) < limit:
            transaction = queue.pop_next()
            if transaction is None:
                break
            self.process(transaction)
            processed.append(transaction)
        return processed
