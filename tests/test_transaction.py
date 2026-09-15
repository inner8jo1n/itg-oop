from datetime import datetime
from decimal import Decimal

import pytest

from bank.accounts.bank_account import BankAccount
from bank.enums import Currency, TransactionStatus, TransactionType
from bank.exceptions import InvalidOperationError
from bank.transactions.transaction import Transaction


class TestTransactionCreation:
    def test_deposit_requires_receiver_only(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        assert tx.sender is None
        assert tx.receiver is account
        assert tx.status == TransactionStatus.PENDING

    def test_deposit_rejects_sender(self, account: BankAccount):
        with pytest.raises(InvalidOperationError):
            Transaction(
                type=TransactionType.DEPOSIT,
                amount=Decimal("10"),
                sender=account,
                receiver=account,
            )

    def test_deposit_requires_receiver(self):
        with pytest.raises(InvalidOperationError):
            Transaction(type=TransactionType.DEPOSIT, amount=Decimal("10"))

    def test_withdrawal_requires_sender_only(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("10"),
            sender=account,
        )
        assert tx.sender is account
        assert tx.receiver is None

    def test_withdrawal_rejects_receiver(self, account: BankAccount):
        with pytest.raises(InvalidOperationError):
            Transaction(
                type=TransactionType.WITHDRAWAL,
                amount=Decimal("10"),
                sender=account,
                receiver=account,
            )

    def test_transfer_requires_both_parties(
        self, account: BankAccount, other_account: BankAccount
    ):
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("10"),
            sender=account,
            receiver=other_account,
        )
        assert tx.sender is account
        assert tx.receiver is other_account

    def test_transfer_rejects_missing_receiver(self, account: BankAccount):
        with pytest.raises(InvalidOperationError):
            Transaction(
                type=TransactionType.TRANSFER,
                amount=Decimal("10"),
                sender=account,
            )

    def test_transfer_rejects_same_account_both_sides(
        self, account: BankAccount
    ):
        with pytest.raises(InvalidOperationError):
            Transaction(
                type=TransactionType.TRANSFER,
                amount=Decimal("10"),
                sender=account,
                receiver=account,
            )

    def test_rejects_currency_mismatch_with_sender(
        self, account: BankAccount, usd_account: BankAccount
    ):
        # account is RUB; a WITHDRAWAL/TRANSFER/EXTERNAL_TRANSFER in
        # USD against it would debit the raw numeric amount as if it
        # were RUB, so this must be rejected at construction time.
        with pytest.raises(InvalidOperationError):
            Transaction(
                type=TransactionType.WITHDRAWAL,
                amount=Decimal("10"),
                currency=Currency.USD,
                sender=account,
            )

    def test_transfer_currency_must_match_sender_not_receiver(
        self, account: BankAccount, usd_account: BankAccount
    ):
        # the receiver may legitimately hold a different currency;
        # TransactionProcessor converts on the credit side, but the
        # transaction's own currency must match the sender's, since
        # the debit side is never converted.
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("10"),
            currency=Currency.RUB,
            sender=account,
            receiver=usd_account,
        )
        assert tx.currency == Currency.RUB

    def test_deposit_currency_may_differ_from_receiver(
        self, usd_account: BankAccount
    ):
        # DEPOSIT has no sender, so no sender-currency check applies;
        # the processor converts into the receiver's currency.
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            currency=Currency.RUB,
            receiver=usd_account,
        )
        assert tx.currency == Currency.RUB

    def test_rejects_non_positive_amount(self, account: BankAccount):
        with pytest.raises(InvalidOperationError):
            Transaction(
                type=TransactionType.DEPOSIT,
                amount=Decimal("0"),
                receiver=account,
            )

    def test_rejects_invalid_type(self, account: BankAccount):
        with pytest.raises(InvalidOperationError):
            Transaction(type="deposit", amount=Decimal("10"), receiver=account)

    def test_rejects_invalid_currency(self, account: BankAccount):
        with pytest.raises(InvalidOperationError):
            Transaction(
                type=TransactionType.DEPOSIT,
                amount=Decimal("10"),
                currency="USD",
                receiver=account,
            )

    def test_rejects_non_bank_account_party(self):
        with pytest.raises(InvalidOperationError):
            Transaction(
                type=TransactionType.DEPOSIT,
                amount=Decimal("10"),
                receiver=object(),
            )

    def test_rejects_bool_priority(self, account: BankAccount):
        with pytest.raises(InvalidOperationError):
            Transaction(
                type=TransactionType.DEPOSIT,
                amount=Decimal("10"),
                receiver=account,
                priority=True,
            )

    def test_auto_generates_transaction_id(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        assert tx.transaction_id

    def test_scheduled_at_starts_as_scheduled(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
            scheduled_at=datetime(2030, 1, 1),
        )
        assert tx.status == TransactionStatus.SCHEDULED

    def test_no_scheduled_at_starts_as_pending(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        assert tx.status == TransactionStatus.PENDING

    def test_fee_starts_at_zero(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        assert tx.fee == Decimal("0")

    def test_attempts_start_at_zero(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        assert tx.attempts == 0


class TestTransactionLifecycle:
    def test_mark_processing_then_completed(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        tx.mark_processing()
        assert tx.status == TransactionStatus.PROCESSING
        tx.mark_completed(at=datetime(2024, 1, 1))
        assert tx.status == TransactionStatus.COMPLETED
        assert tx.processed_at == datetime(2024, 1, 1)

    def test_mark_processing_then_failed(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        tx.mark_processing()
        tx.mark_failed("boom", at=datetime(2024, 1, 1))
        assert tx.status == TransactionStatus.FAILED
        assert tx.failure_reason == "boom"
        assert tx.processed_at == datetime(2024, 1, 1)

    def test_cannot_process_twice(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        tx.mark_processing()
        with pytest.raises(InvalidOperationError):
            tx.mark_processing()

    def test_cannot_complete_without_processing(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        with pytest.raises(InvalidOperationError):
            tx.mark_completed()

    def test_cannot_fail_without_processing(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        with pytest.raises(InvalidOperationError):
            tx.mark_failed("boom")

    def test_cancel_pending(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        tx.mark_cancelled()
        assert tx.status == TransactionStatus.CANCELLED

    def test_cancel_scheduled(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
            scheduled_at=datetime(2030, 1, 1),
        )
        tx.mark_cancelled()
        assert tx.status == TransactionStatus.CANCELLED

    def test_cannot_cancel_while_processing(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        tx.mark_processing()
        with pytest.raises(InvalidOperationError):
            tx.mark_cancelled()

    def test_cannot_cancel_completed(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        tx.mark_processing()
        tx.mark_completed()
        with pytest.raises(InvalidOperationError):
            tx.mark_cancelled()

    def test_record_attempt_increments_counter(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        tx.record_attempt()
        tx.record_attempt()
        assert tx.attempts == 2

    def test_full_flow_from_scheduled_to_completed(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
            scheduled_at=datetime(2024, 1, 1),
        )
        assert tx.status == TransactionStatus.SCHEDULED
        tx.mark_processing()
        assert tx.status == TransactionStatus.PROCESSING
        tx.mark_completed(at=datetime(2024, 1, 1, 1))
        assert tx.status == TransactionStatus.COMPLETED
        assert tx.processed_at == datetime(2024, 1, 1, 1)


def _make_pending(account: BankAccount) -> Transaction:
    return Transaction(
        type=TransactionType.DEPOSIT, amount=Decimal("10"), receiver=account
    )


def _make_completed(account: BankAccount) -> Transaction:
    tx = _make_pending(account)
    tx.mark_processing()
    tx.mark_completed()
    return tx


def _make_failed(account: BankAccount) -> Transaction:
    tx = _make_pending(account)
    tx.mark_processing()
    tx.mark_failed("boom")
    return tx


def _make_cancelled(account: BankAccount) -> Transaction:
    tx = _make_pending(account)
    tx.mark_cancelled()
    return tx


_TERMINAL_BUILDERS = {
    "completed": _make_completed,
    "failed": _make_failed,
    "cancelled": _make_cancelled,
}
_TRANSITIONS = {
    "mark_processing": lambda tx: tx.mark_processing(),
    "mark_completed": lambda tx: tx.mark_completed(),
    "mark_failed": lambda tx: tx.mark_failed("again"),
    "mark_cancelled": lambda tx: tx.mark_cancelled(),
}


class TestTerminalStatusesRejectAllTransitions:
    """
    COMPLETED, FAILED and CANCELLED must be true dead ends: none of
    the four mutating transitions may be applied from any of them.
    """

    @pytest.mark.parametrize("transition_name", sorted(_TRANSITIONS))
    @pytest.mark.parametrize("status_name", sorted(_TERMINAL_BUILDERS))
    def test_rejects_transition_from_terminal_status(
        self,
        account: BankAccount,
        status_name: str,
        transition_name: str,
    ):
        tx = _TERMINAL_BUILDERS[status_name](account)
        transition = _TRANSITIONS[transition_name]
        with pytest.raises(InvalidOperationError):
            transition(tx)
        assert tx.status.value == status_name


class TestTransactionSummaryAndString:
    def test_get_summary_contains_expected_fields(
        self, account: BankAccount, other_account: BankAccount
    ):
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("10"),
            currency=Currency.RUB,
            sender=account,
            receiver=other_account,
            priority=2,
        )
        summary = tx.get_summary()
        assert summary["transaction_id"] == tx.transaction_id
        assert summary["type"] == "transfer"
        assert summary["amount"] == Decimal("10")
        assert summary["currency"] == "RUB"
        assert summary["sender"] == account.account_id
        assert summary["receiver"] == other_account.account_id
        assert summary["status"] == "pending"
        assert summary["priority"] == 2

    def test_str_shows_external_for_missing_party(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        text = str(tx)
        assert "EXTERNAL" in text
        assert account.account_id[-4:] in text

    def test_str_shows_failure_reason(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        tx.mark_processing()
        tx.mark_failed("insufficient funds")
        assert "insufficient funds" in str(tx)
