from datetime import datetime
from decimal import Decimal

import pytest

from bank.accounts.bank_account import BankAccount
from bank.enums import TransactionType
from bank.exceptions import InvalidOperationError, TransactionNotFoundError
from bank.transactions.transaction import Transaction
from bank.transactions.transaction_queue import TransactionQueue

DAY_TIME = datetime(2024, 1, 1, 12, 0, 0)


def make_deposit(
    receiver: BankAccount,
    priority: int = 0,
    scheduled_at=None,
    created_at=None,
) -> Transaction:
    return Transaction(
        type=TransactionType.DEPOSIT,
        amount=Decimal("10"),
        receiver=receiver,
        priority=priority,
        scheduled_at=scheduled_at,
        created_at=created_at,
    )


class TestEnqueue:
    def test_adds_transaction(self, account: BankAccount):
        queue = TransactionQueue(clock=lambda: DAY_TIME)
        tx = make_deposit(account)
        queue.enqueue(tx)
        assert len(queue) == 1
        assert queue.transactions[tx.transaction_id] is tx

    def test_rejects_non_transaction(self):
        queue = TransactionQueue(clock=lambda: DAY_TIME)
        with pytest.raises(InvalidOperationError):
            queue.enqueue(object())

    def test_rejects_duplicate(self, account: BankAccount):
        queue = TransactionQueue(clock=lambda: DAY_TIME)
        tx = make_deposit(account)
        queue.enqueue(tx)
        with pytest.raises(InvalidOperationError):
            queue.enqueue(tx)

    @pytest.mark.parametrize(
        "make_terminal",
        [
            lambda tx: (tx.mark_processing(), tx.mark_completed()),
            lambda tx: (tx.mark_processing(), tx.mark_failed("boom")),
            lambda tx: tx.mark_cancelled(),
        ],
        ids=["completed", "failed", "cancelled"],
    )
    def test_rejects_already_terminal_transaction(
        self, account: BankAccount, make_terminal
    ):
        queue = TransactionQueue(clock=lambda: DAY_TIME)
        tx = make_deposit(account)
        make_terminal(tx)
        with pytest.raises(InvalidOperationError):
            queue.enqueue(tx)


class TestPopNext:
    def test_returns_none_when_empty(self):
        queue = TransactionQueue(clock=lambda: DAY_TIME)
        assert queue.pop_next() is None

    def test_higher_priority_popped_first(self, account: BankAccount):
        queue = TransactionQueue(clock=lambda: DAY_TIME)
        low = make_deposit(account, priority=1)
        high = make_deposit(account, priority=5)
        queue.enqueue(low)
        queue.enqueue(high)
        assert queue.pop_next() is high
        assert queue.pop_next() is low

    def test_ties_broken_by_creation_order(self, account: BankAccount):
        queue = TransactionQueue(clock=lambda: DAY_TIME)
        first = make_deposit(
            account, created_at=datetime(2024, 1, 1, 10, 0, 0)
        )
        second = make_deposit(
            account, created_at=datetime(2024, 1, 1, 11, 0, 0)
        )
        queue.enqueue(second)
        queue.enqueue(first)
        assert queue.pop_next() is first
        assert queue.pop_next() is second

    def test_pop_removes_from_queue(self, account: BankAccount):
        queue = TransactionQueue(clock=lambda: DAY_TIME)
        tx = make_deposit(account)
        queue.enqueue(tx)
        queue.pop_next()
        assert len(queue) == 0

    def test_scheduled_not_ready_is_skipped(self, account: BankAccount):
        queue = TransactionQueue(clock=lambda: DAY_TIME)
        future = make_deposit(
            account, scheduled_at=datetime(2024, 1, 1, 13, 0, 0)
        )
        queue.enqueue(future)
        assert queue.pop_next() is None
        assert len(queue) == 1

    def test_scheduled_ready_is_popped(self, account: BankAccount):
        queue = TransactionQueue(clock=lambda: DAY_TIME)
        due = make_deposit(
            account, scheduled_at=datetime(2024, 1, 1, 11, 0, 0)
        )
        queue.enqueue(due)
        assert queue.pop_next() is due

    def test_scheduled_before_ready_is_skipped_for_pending(
        self, account: BankAccount
    ):
        queue = TransactionQueue(clock=lambda: DAY_TIME)
        future = make_deposit(
            account, scheduled_at=datetime(2024, 1, 1, 13, 0, 0)
        )
        ready = make_deposit(account)
        queue.enqueue(future)
        queue.enqueue(ready)
        assert queue.pop_next() is ready
        assert queue.pop_next() is None


class TestCancel:
    def test_cancels_pending_transaction(self, account: BankAccount):
        queue = TransactionQueue(clock=lambda: DAY_TIME)
        tx = make_deposit(account)
        queue.enqueue(tx)
        queue.cancel(tx.transaction_id)
        assert tx.status.value == "cancelled"
        assert len(queue) == 0
        assert queue.pop_next() is None

    def test_rejects_unknown_transaction_id(self):
        queue = TransactionQueue(clock=lambda: DAY_TIME)
        with pytest.raises(TransactionNotFoundError):
            queue.cancel("does-not-exist")

    def test_cannot_cancel_after_pop(self, account: BankAccount):
        queue = TransactionQueue(clock=lambda: DAY_TIME)
        tx = make_deposit(account)
        queue.enqueue(tx)
        queue.pop_next()
        tx.mark_processing()
        with pytest.raises(InvalidOperationError):
            queue.cancel(tx.transaction_id)

    def test_cancel_after_pop_but_before_processing_does_not_crash(
        self, account: BankAccount
    ):
        queue = TransactionQueue(clock=lambda: DAY_TIME)
        tx = make_deposit(account)
        queue.enqueue(tx)
        popped = queue.pop_next()
        assert popped is tx
        assert tx.status.value == "pending"
        queue.cancel(tx.transaction_id)
        assert tx.status.value == "cancelled"
