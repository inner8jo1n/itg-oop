from collections.abc import Callable
from datetime import datetime

from bank.enums import TransactionStatus
from bank.exceptions import InvalidOperationError, TransactionNotFoundError
from bank.transactions.transaction import Transaction


class TransactionQueue:
    """
    Holds transactions awaiting processing, releasing the
    highest-priority ready transaction first (ties broken by
    creation order) and honoring deferred execution times.
    """

    def __init__(self, clock: Callable[[], datetime] = datetime.now):
        """
        Create an empty transaction queue.

        :param clock: callable returning the current datetime, used
            to decide whether a scheduled transaction is due
        """
        self._clock = clock
        self._transactions: dict[str, Transaction] = {}
        self._order: list[str] = []

    def __len__(self) -> int:
        """
        Get the number of transactions still waiting in the queue.

        :return: count of queued transactions
        """
        return len(self._order)

    @property
    def transactions(self) -> dict[str, Transaction]:
        """
        Get a copy of all transactions ever enqueued, keyed by id,
        including ones already popped, cancelled or processed.

        :return: mapping of transaction id to transaction
        """
        return dict(self._transactions)

    def enqueue(self, transaction: Transaction) -> None:
        """
        Add a transaction to the queue.

        :param transaction: transaction to enqueue; must be PENDING
            or SCHEDULED and not already in this queue
        :return: None
        """
        if not isinstance(transaction, Transaction):
            raise InvalidOperationError(
                f"Expected a Transaction, got {transaction!r}"
            )
        if transaction.transaction_id in self._transactions:
            raise InvalidOperationError(
                f"Transaction {transaction.transaction_id} is "
                f"already in this queue"
            )
        if transaction.status not in (
            TransactionStatus.PENDING,
            TransactionStatus.SCHEDULED,
        ):
            raise InvalidOperationError(
                f"Cannot enqueue transaction "
                f"{transaction.transaction_id} in status "
                f"{transaction.status.value}"
            )
        self._transactions[transaction.transaction_id] = transaction
        self._order.append(transaction.transaction_id)

    def cancel(self, transaction_id: str) -> None:
        """
        Cancel a pending or scheduled transaction, removing it from
        the ready order so it will never be popped. Safe to call on
        a transaction that was already popped by `pop_next` but not
        yet marked as processing.

        :param transaction_id: id of the transaction to cancel
        :return: None
        """
        transaction = self._get(transaction_id)
        transaction.mark_cancelled(at=self._clock())
        if transaction_id in self._order:
            self._order.remove(transaction_id)

    def _get(self, transaction_id: str) -> Transaction:
        """
        Look up a transaction by id or raise if it does not exist.

        :param transaction_id: transaction identifier
        :return: the matching transaction
        """
        transaction = self._transactions.get(transaction_id)
        if transaction is None:
            raise TransactionNotFoundError(
                f"Transaction {transaction_id} not found"
            )
        return transaction

    def _is_ready(self, transaction: Transaction) -> bool:
        """
        Check whether a transaction is currently eligible to be
        popped: pending, or scheduled with its due time reached.

        :param transaction: transaction to check
        :return: True if ready to be processed now
        """
        if transaction.status == TransactionStatus.PENDING:
            return True
        if transaction.status == TransactionStatus.SCHEDULED:
            return (
                transaction.scheduled_at is not None
                and transaction.scheduled_at <= self._clock()
            )
        return False

    def pop_next(self) -> Transaction | None:
        """
        Remove and return the highest-priority ready transaction,
        breaking ties by earliest creation time.

        :return: the next transaction to process, or None if no
            queued transaction is currently ready
        """
        ready_ids = [
            transaction_id
            for transaction_id in self._order
            if self._is_ready(self._transactions[transaction_id])
        ]
        if not ready_ids:
            return None
        chosen_id = min(
            ready_ids,
            key=lambda transaction_id: (
                -self._transactions[transaction_id].priority,
                self._transactions[transaction_id].created_at,
            ),
        )
        self._order.remove(chosen_id)
        return self._transactions[chosen_id]
