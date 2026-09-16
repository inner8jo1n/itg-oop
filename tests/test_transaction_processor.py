from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from bank.accounts.bank_account import BankAccount
from bank.accounts.premium_account import PremiumAccount
from bank.enums import Currency, TransactionType
from bank.exceptions import (
    ExchangeRateNotFoundError,
    InvalidOperationError,
    OperationNotAllowedError,
)
from bank.transactions.transaction import Transaction
from bank.transactions.transaction_processor import TransactionProcessor
from bank.transactions.transaction_queue import TransactionQueue


def bind_flaky_hook(account: BankAccount, fail_times: int) -> None:
    """
    Make the first `fail_times` operations on `account` raise
    OperationNotAllowedError, then let the rest through.
    """
    calls = {"n": 0}

    def before_operation() -> None:
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise OperationNotAllowedError("temporarily unavailable")

    account._bind_bank_hooks(
        before_operation=before_operation, after_withdraw=lambda amount: None
    )


def bind_fail_after(account: BankAccount, allow_calls: int) -> None:
    """
    Let the first `allow_calls` operations on `account` succeed,
    then raise OperationNotAllowedError on every one after that.
    """
    calls = {"n": 0}

    def before_operation() -> None:
        calls["n"] += 1
        if calls["n"] > allow_calls:
            raise OperationNotAllowedError("sender blocked for refund")

    account._bind_bank_hooks(
        before_operation=before_operation, after_withdraw=lambda amount: None
    )


class TestConstruction:
    def test_rejects_zero_max_retries(self):
        with pytest.raises(InvalidOperationError):
            TransactionProcessor(max_retries=0)

    def test_rejects_negative_max_retries(self):
        with pytest.raises(InvalidOperationError):
            TransactionProcessor(max_retries=-1)

    def test_rejects_non_int_max_retries(self):
        with pytest.raises(InvalidOperationError):
            TransactionProcessor(max_retries="3")

    def test_accepts_positive_max_retries(self):
        assert TransactionProcessor(max_retries=1) is not None

    def test_rejects_negative_external_transfer_fee_rate(self):
        with pytest.raises(InvalidOperationError):
            TransactionProcessor(external_transfer_fee_rate=Decimal("-0.01"))

    def test_accepts_zero_external_transfer_fee_rate(self):
        processor = TransactionProcessor(
            external_transfer_fee_rate=Decimal("0")
        )
        assert processor is not None

    def test_rejects_negative_exchange_rate(self):
        with pytest.raises(InvalidOperationError):
            TransactionProcessor(
                exchange_rates={(Currency.RUB, Currency.USD): Decimal("-0.01")}
            )

    def test_rejects_zero_exchange_rate(self):
        with pytest.raises(InvalidOperationError):
            TransactionProcessor(
                exchange_rates={(Currency.RUB, Currency.USD): Decimal("0")}
            )

    def test_accepts_positive_exchange_rate(self):
        processor = TransactionProcessor(
            exchange_rates={(Currency.RUB, Currency.USD): Decimal("0.01")}
        )
        assert processor is not None


class TestProcessRejectsNonTransaction:
    def test_rejects_non_transaction(self):
        with pytest.raises(InvalidOperationError):
            TransactionProcessor().process(object())

    def test_reprocessing_a_completed_transaction_raises_uncaught(
        self, account: BankAccount
    ):
        # Calling process() twice on the same object is a caller
        # error (a Transaction is meant to be processed once), not a
        # business-rule failure like insufficient funds. It must
        # raise immediately rather than be silently turned into a
        # second "failed" status, which would misreport a
        # transaction that already succeeded.
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        processor = TransactionProcessor()
        processor.process(tx)
        assert tx.status.value == "completed"
        with pytest.raises(InvalidOperationError):
            processor.process(tx)
        assert tx.status.value == "completed"

    def test_rejects_scheduled_transaction_processed_early(
        self, account: BankAccount
    ):
        # process() must not execute a SCHEDULED transaction ahead
        # of its scheduled_at, even when called directly instead of
        # via TransactionQueue.pop_next() (which normally gates on
        # readiness before a transaction ever reaches process()).
        now = datetime(2024, 1, 1, 12, 0, 0)
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
            scheduled_at=now + timedelta(hours=1),
            created_at=now,
        )
        processor = TransactionProcessor(clock=lambda: now)
        with pytest.raises(InvalidOperationError):
            processor.process(tx)
        assert tx.status.value == "scheduled"
        assert account.balance == Decimal("100")

    def test_processes_scheduled_transaction_once_due(
        self, account: BankAccount
    ):
        now = datetime(2024, 1, 1, 12, 0, 0)
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
            scheduled_at=now,
            created_at=now,
        )
        processor = TransactionProcessor(clock=lambda: now)
        processor.process(tx)
        assert tx.status.value == "completed"
        assert account.balance == Decimal("110")


class TestDeposit:
    def test_credits_receiver(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("50"),
            receiver=account,
        )
        TransactionProcessor().process(tx)
        assert tx.status.value == "completed"
        assert account.balance == Decimal("150")
        assert tx.fee == Decimal("0")

    def test_fails_on_frozen_receiver(self, account: BankAccount):
        account.freeze()
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("50"),
            receiver=account,
        )
        TransactionProcessor().process(tx)
        assert tx.status.value == "failed"
        assert "frozen" in tx.failure_reason
        assert tx.attempts == 1


class TestWithdrawal:
    def test_debits_sender(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("30"),
            sender=account,
        )
        TransactionProcessor().process(tx)
        assert tx.status.value == "completed"
        assert account.balance == Decimal("70")
        assert tx.fee == Decimal("0")

    def test_records_account_fee_for_premium_sender(
        self, premium_account: PremiumAccount
    ):
        # premium_account fixture charges a fixed transaction_fee of
        # 10 on every withdrawal; this processor has no withdrawal
        # fee of its own, but tx.fee must still reflect the 10 that
        # was actually debited on top of the requested amount.
        tx = Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("30"),
            sender=premium_account,
        )
        TransactionProcessor().process(tx)
        assert tx.status.value == "completed"
        assert premium_account.balance == Decimal("960")
        assert tx.fee == Decimal("10")

    def test_fails_on_insufficient_funds(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("1000"),
            sender=account,
        )
        TransactionProcessor().process(tx)
        assert tx.status.value == "failed"
        assert "Insufficient funds" in tx.failure_reason
        assert tx.attempts == 1


class TestTransfer:
    def test_moves_funds_without_fee(
        self, account: BankAccount, other_account: BankAccount
    ):
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("40"),
            sender=account,
            receiver=other_account,
        )
        TransactionProcessor().process(tx)
        assert tx.status.value == "completed"
        assert tx.fee == Decimal("0")
        assert account.balance == Decimal("60")
        assert other_account.balance == Decimal("540")

    def test_rejects_negative_balance_for_regular_account(
        self, account: BankAccount, other_account: BankAccount
    ):
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("1000"),
            sender=account,
            receiver=other_account,
        )
        TransactionProcessor().process(tx)
        assert tx.status.value == "failed"
        assert account.balance == Decimal("100")

    def test_refunds_sender_if_frozen_receiver_rejects_deposit(
        self, account: BankAccount, other_account: BankAccount
    ):
        other_account.freeze()
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("40"),
            sender=account,
            receiver=other_account,
        )
        TransactionProcessor().process(tx)
        assert tx.status.value == "failed"
        assert account.balance == Decimal("100")

    def test_refund_restores_full_amount_for_premium_sender(
        self, premium_account: PremiumAccount, other_account: BankAccount
    ):
        # premium_account's own transaction_fee (10) is deducted by
        # its withdraw() on top of whatever was requested, so the
        # refund must give back the actual amount debited, not just
        # what the transaction asked to withdraw.
        other_account.freeze()
        balance_before = premium_account.balance
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("40"),
            sender=premium_account,
            receiver=other_account,
        )
        TransactionProcessor().process(tx)
        assert tx.status.value == "failed"
        assert premium_account.balance == balance_before

    def test_failed_refund_is_non_retryable(
        self, account: BankAccount, other_account: BankAccount
    ):
        other_account.freeze()
        # allow_calls=1: the initial withdraw succeeds, but the
        # compensating refund deposit (the 2nd call on `account`)
        # raises, even though it's normally a retryable error type.
        bind_fail_after(account, allow_calls=1)
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("40"),
            sender=account,
            receiver=other_account,
        )
        TransactionProcessor(max_retries=3).process(tx)
        assert tx.status.value == "failed"
        assert tx.attempts == 1
        assert "Refund to" in tx.failure_reason

    def test_allows_overdraft_for_premium_sender(
        self, premium_account: PremiumAccount, other_account: BankAccount
    ):
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("1200"),
            sender=premium_account,
            receiver=other_account,
        )
        TransactionProcessor().process(tx)
        assert tx.status.value == "completed"
        # premium_account fixture also charges a fixed transaction_fee
        # of 10 on top of the withdrawn amount: 1000 - 1200 - 10 = -210
        assert premium_account.balance == Decimal("-210")
        # tx.fee reflects the actual total debited beyond the
        # principal (1210 - 1200), i.e. the account's own fee, since
        # this processor charges nothing extra for internal transfers
        assert tx.fee == Decimal("10")


class TestExternalTransfer:
    def test_charges_fee_and_credits_full_amount(
        self, account: BankAccount, other_account: BankAccount
    ):
        processor = TransactionProcessor(
            external_transfer_fee_rate=Decimal("0.1")
        )
        tx = Transaction(
            type=TransactionType.EXTERNAL_TRANSFER,
            amount=Decimal("40"),
            sender=account,
            receiver=other_account,
        )
        processor.process(tx)
        assert tx.status.value == "completed"
        assert tx.fee == Decimal("4.0")
        assert account.balance == Decimal("56")
        assert other_account.balance == Decimal("540")

    def test_internal_transfer_has_no_fee_but_external_does(
        self, account: BankAccount, other_account: BankAccount
    ):
        processor = TransactionProcessor(
            external_transfer_fee_rate=Decimal("0.1")
        )
        internal = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("10"),
            sender=account,
            receiver=other_account,
        )
        processor.process(internal)
        assert internal.fee == Decimal("0")

    def test_premium_account_fee_stacks_with_processor_fee(
        self, premium_account: PremiumAccount, other_account: BankAccount
    ):
        # premium_account fixture: initial_balance=1000,
        # transaction_fee=10 (its own fixed per-withdrawal fee).
        # Processor fee here is 40 * 0.1 = 4. PremiumAccount.withdraw
        # adds its own 10 on top of what it's asked to withdraw
        # (40 + 4 = 44), so the account is actually debited 54.
        # tx.fee reflects that full 14 (4 processor + 10 account),
        # not just the processor's own cut, so the transaction's own
        # data stays truthful about what was actually charged.
        processor = TransactionProcessor(
            external_transfer_fee_rate=Decimal("0.1")
        )
        tx = Transaction(
            type=TransactionType.EXTERNAL_TRANSFER,
            amount=Decimal("40"),
            sender=premium_account,
            receiver=other_account,
        )
        processor.process(tx)
        assert tx.status.value == "completed"
        assert tx.fee == Decimal("14.0")
        assert premium_account.balance == Decimal("946")
        assert other_account.balance == Decimal("540")


class TestCurrencyConversion:
    def test_converts_amount_into_receiver_currency(
        self, account: BankAccount, usd_account: BankAccount
    ):
        processor = TransactionProcessor(
            exchange_rates={(Currency.RUB, Currency.USD): Decimal("0.01")}
        )
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("100"),
            currency=Currency.RUB,
            sender=account,
            receiver=usd_account,
        )
        processor.process(tx)
        assert tx.status.value == "completed"
        assert usd_account.balance == Decimal("101.00")

    def test_missing_rate_fails_transaction(
        self, account: BankAccount, usd_account: BankAccount
    ):
        processor = TransactionProcessor(exchange_rates={})
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("100"),
            currency=Currency.RUB,
            sender=account,
            receiver=usd_account,
        )
        processor.process(tx)
        assert tx.status.value == "failed"
        assert account.balance == Decimal("100")

    def test_convert_raises_directly_without_rate(self):
        processor = TransactionProcessor()
        with pytest.raises(ExchangeRateNotFoundError):
            processor.convert(Decimal("10"), Currency.RUB, Currency.USD)

    def test_convert_same_currency_is_identity(self):
        processor = TransactionProcessor()
        result = processor.convert(Decimal("10"), Currency.RUB, Currency.RUB)
        assert result == Decimal("10")


class TestRetries:
    def test_succeeds_after_transient_failures(self, account: BankAccount):
        bind_flaky_hook(account, fail_times=2)
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        TransactionProcessor(max_retries=3).process(tx)
        assert tx.status.value == "completed"
        assert tx.attempts == 3
        assert account.balance == Decimal("110")

    def test_fails_after_exhausting_retries(self, account: BankAccount):
        bind_flaky_hook(account, fail_times=10)
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        TransactionProcessor(max_retries=3).process(tx)
        assert tx.status.value == "failed"
        assert tx.attempts == 3
        assert "Failed after 3 attempts" in tx.failure_reason
        assert account.balance == Decimal("100")

    def test_non_retryable_error_fails_on_first_attempt(
        self, account: BankAccount
    ):
        tx = Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("1000"),
            sender=account,
        )
        TransactionProcessor(max_retries=3).process(tx)
        assert tx.status.value == "failed"
        assert tx.attempts == 1


class TestProcessQueue:
    def test_processes_all_ready_transactions(
        self, account: BankAccount, other_account: BankAccount
    ):
        queue = TransactionQueue()
        deposit = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        transfer = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("5"),
            sender=account,
            receiver=other_account,
        )
        queue.enqueue(deposit)
        queue.enqueue(transfer)
        processed = TransactionProcessor().process_queue(queue)
        assert len(processed) == 2
        assert all(tx.status.value == "completed" for tx in processed)
        assert len(queue) == 0

    def test_respects_limit(self, account: BankAccount):
        queue = TransactionQueue()
        for _ in range(3):
            queue.enqueue(
                Transaction(
                    type=TransactionType.DEPOSIT,
                    amount=Decimal("1"),
                    receiver=account,
                )
            )
        processed = TransactionProcessor().process_queue(queue, limit=2)
        assert len(processed) == 2
        assert len(queue) == 1

    def test_empty_queue_returns_empty_list(self):
        queue = TransactionQueue()
        assert TransactionProcessor().process_queue(queue) == []
