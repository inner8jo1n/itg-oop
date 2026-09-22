from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from bank.accounts.bank_account import BankAccount
from bank.accounts.premium_account import PremiumAccount
from bank.audit.audit_log import AuditLog
from bank.audit.risk_analyzer import RiskAnalyzer
from bank.bank import Bank
from bank.enums import AuditSeverity, Currency, TransactionType
from bank.exceptions import (
    ExchangeRateNotFoundError,
    InsufficientFundsError,
    InvalidOperationError,
    OperationNotAllowedError,
)
from bank.transactions.transaction import Transaction
from bank.transactions.transaction_processor import TransactionProcessor
from bank.transactions.transaction_queue import TransactionQueue

DAY_TIME = datetime(2024, 1, 1, 12, 0, 0)


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


def make_processor(**kwargs) -> TransactionProcessor:
    """
    Build a TransactionProcessor defaulting to a fixed daytime clock.
    Risk analysis is now mandatory (see TransactionProcessor.__init__),
    and its default RiskAnalyzer uses this same clock to decide
    night_operation - without pinning it, a test run during real
    night hours could unpredictably flag transactions as suspicious
    or even block them. Tests that need a different clock, or that
    supply their own risk_analyzer, still override it explicitly.
    """
    kwargs.setdefault("clock", lambda: DAY_TIME)
    return TransactionProcessor(**kwargs)


class TestConstruction:
    def test_rejects_zero_max_retries(self):
        with pytest.raises(InvalidOperationError):
            make_processor(max_retries=0)

    def test_rejects_negative_max_retries(self):
        with pytest.raises(InvalidOperationError):
            make_processor(max_retries=-1)

    def test_rejects_non_int_max_retries(self):
        with pytest.raises(InvalidOperationError):
            make_processor(max_retries="3")

    def test_accepts_positive_max_retries(self):
        assert make_processor(max_retries=1) is not None

    def test_rejects_negative_external_transfer_fee_rate(self):
        with pytest.raises(InvalidOperationError):
            make_processor(external_transfer_fee_rate=Decimal("-0.01"))

    def test_accepts_zero_external_transfer_fee_rate(self):
        processor = make_processor(
            external_transfer_fee_rate=Decimal("0")
        )
        assert processor is not None

    def test_rejects_negative_exchange_rate(self):
        with pytest.raises(InvalidOperationError):
            make_processor(
                exchange_rates={(Currency.RUB, Currency.USD): Decimal("-0.01")}
            )

    def test_rejects_zero_exchange_rate(self):
        with pytest.raises(InvalidOperationError):
            make_processor(
                exchange_rates={(Currency.RUB, Currency.USD): Decimal("0")}
            )

    def test_accepts_positive_exchange_rate(self):
        processor = make_processor(
            exchange_rates={(Currency.RUB, Currency.USD): Decimal("0.01")}
        )
        assert processor is not None


class TestProcessRejectsNonTransaction:
    def test_rejects_non_transaction(self):
        with pytest.raises(InvalidOperationError):
            make_processor().process(object())

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
        processor = make_processor()
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
        processor = make_processor(clock=lambda: now)
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
        processor = make_processor(clock=lambda: now)
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
        make_processor().process(tx)
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
        make_processor().process(tx)
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
        make_processor().process(tx)
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
        make_processor().process(tx)
        assert tx.status.value == "completed"
        assert premium_account.balance == Decimal("960")
        assert tx.fee == Decimal("10")

    def test_fails_on_insufficient_funds(self, account: BankAccount):
        tx = Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("1000"),
            sender=account,
        )
        make_processor().process(tx)
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
        make_processor().process(tx)
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
        make_processor().process(tx)
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
        make_processor().process(tx)
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
        make_processor().process(tx)
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
        make_processor(max_retries=3).process(tx)
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
        make_processor().process(tx)
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
        processor = make_processor(
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
        processor = make_processor(
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
        processor = make_processor(
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
        processor = make_processor(
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

    def test_credited_amount_reflects_converted_value(
        self, account: BankAccount, usd_account: BankAccount
    ):
        processor = make_processor(
            exchange_rates={(Currency.RUB, Currency.USD): Decimal("0.011")}
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
        # tx.amount stays 100 (RUB, sender's currency); the amount
        # actually credited to the USD receiver is what was converted
        assert tx.amount == Decimal("100")
        assert tx.credited_amount == Decimal("1.100")

    def test_credited_amount_is_none_for_withdrawal(
        self, account: BankAccount
    ):
        tx = Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("10"),
            sender=account,
        )
        make_processor().process(tx)
        assert tx.status.value == "completed"
        assert tx.credited_amount is None

    def test_credited_amount_stays_none_when_deposit_fails(
        self, account: BankAccount, usd_account: BankAccount
    ):
        usd_account.freeze()
        processor = make_processor(
            exchange_rates={(Currency.RUB, Currency.USD): Decimal("0.01")}
        )
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("10"),
            currency=Currency.RUB,
            sender=account,
            receiver=usd_account,
        )
        processor.process(tx)
        assert tx.status.value == "failed"
        assert tx.credited_amount is None

    def test_missing_rate_fails_transaction(
        self, account: BankAccount, usd_account: BankAccount
    ):
        processor = make_processor(exchange_rates={})
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
        processor = make_processor()
        with pytest.raises(ExchangeRateNotFoundError):
            processor.convert(Decimal("10"), Currency.RUB, Currency.USD)

    def test_convert_same_currency_is_identity(self):
        processor = make_processor()
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
        make_processor(max_retries=3).process(tx)
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
        make_processor(max_retries=3).process(tx)
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
        make_processor(max_retries=3).process(tx)
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
        processed = make_processor().process_queue(queue)
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
        processed = make_processor().process_queue(queue, limit=2)
        assert len(processed) == 2
        assert len(queue) == 1

    def test_empty_queue_returns_empty_list(self):
        queue = TransactionQueue()
        assert make_processor().process_queue(queue) == []


class TestRiskAnalyzerIntegration:
    def test_blocks_high_risk_transaction_before_touching_accounts(
        self, account: BankAccount, other_account: BankAccount
    ):
        risk_analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("50"), clock=lambda: DAY_TIME
        )
        processor = make_processor(risk_analyzer=risk_analyzer)
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("60"),
            sender=account,
            receiver=other_account,
        )
        processor.process(tx)
        assert tx.status.value == "failed"
        assert "Blocked by risk analysis" in tx.failure_reason
        assert account.balance == Decimal("100")
        assert other_account.balance == Decimal("500")

    def test_blocked_transaction_never_calls_the_handler(
        self, account: BankAccount, other_account: BankAccount
    ):
        risk_analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("50"), clock=lambda: DAY_TIME
        )
        processor = make_processor(risk_analyzer=risk_analyzer)
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("60"),
            sender=account,
            receiver=other_account,
        )
        processor.process(tx)
        assert tx.attempts == 0

    def test_allows_low_risk_transaction_through(
        self, account: BankAccount, other_account: BankAccount
    ):
        risk_analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("1000000"), clock=lambda: DAY_TIME
        )
        processor = make_processor(risk_analyzer=risk_analyzer)
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("10"),
            sender=account,
            receiver=other_account,
        )
        processor.process(tx)
        assert tx.status.value == "completed"

    def test_medium_risk_transaction_is_not_blocked(
        self, account: BankAccount, other_account: BankAccount
    ):
        risk_analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("1000000"), clock=lambda: DAY_TIME
        )
        processor = make_processor(risk_analyzer=risk_analyzer)
        # first transfer to other_account is a new recipient: exactly
        # one risk factor, MEDIUM, must still go through
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("10"),
            sender=account,
            receiver=other_account,
        )
        processor.process(tx)
        assert tx.status.value == "completed"

    def test_no_explicit_risk_analyzer_still_blocks_high_risk_transaction(
        self, account: BankAccount, other_account: BankAccount
    ):
        # Regression test: TransactionProcessor() with no explicit
        # risk_analyzer must still construct a default RiskAnalyzer
        # and use it - there is no constructor path that skips risk
        # checking entirely. large_amount + new_recipient (first
        # transfer between these accounts) is HIGH under default
        # thresholds.
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("1000000"),
            sender=account,
            receiver=other_account,
        )
        make_processor().process(tx)
        assert tx.status.value == "failed"
        assert "Blocked by risk analysis" in tx.failure_reason
        assert account.balance == Decimal("100")

    def test_resubmitting_a_blocked_transfer_is_blocked_again(
        self, account: BankAccount, other_account: BankAccount
    ):
        # Regression test: a HIGH-risk transfer to a brand-new
        # recipient must not be "learnable" from the blocked attempt
        # itself. If it were, resubmitting the exact same transfer
        # would drop new_recipient (since the recipient was "seen"
        # by the blocked attempt) and let a merely-MEDIUM large
        # amount through on the second try.
        risk_analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("50"), clock=lambda: DAY_TIME
        )
        processor = make_processor(risk_analyzer=risk_analyzer)
        first = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("60"),
            sender=account,
            receiver=other_account,
        )
        processor.process(first)
        assert first.status.value == "failed"

        second = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("60"),
            sender=account,
            receiver=other_account,
        )
        processor.process(second)
        assert second.status.value == "failed"
        assert "Blocked by risk analysis" in second.failure_reason
        assert account.balance == Decimal("100")
        assert other_account.balance == Decimal("500")


class TestBankHookAssessedBy:
    def test_hook_always_runs_and_receives_the_assessed_by_token(
        self, account: BankAccount
    ):
        # The before_withdraw hook is never unconditionally silenced:
        # it always runs, and is told which analyzer (if any) already
        # assessed this withdrawal, so it alone decides whether that
        # is good enough to skip its own check.
        seen = []
        account._bind_bank_hooks(
            before_operation=lambda: None,
            after_withdraw=lambda amount: None,
            before_withdraw=lambda amount, assessed_by: seen.append(
                assessed_by
            ),
        )
        risk_analyzer = RiskAnalyzer(clock=lambda: DAY_TIME)
        processor = TransactionProcessor(
            risk_analyzer=risk_analyzer, clock=lambda: DAY_TIME
        )
        tx = Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("10"),
            sender=account,
        )
        processor.process(tx)
        assert tx.status.value == "completed"
        assert seen == [risk_analyzer]

        account.withdraw(Decimal("5"))
        assert seen == [risk_analyzer, None]

    def test_token_reset_even_when_processor_driven_withdraw_fails(
        self, account: BankAccount
    ):
        seen = []
        account._bind_bank_hooks(
            before_operation=lambda: None,
            after_withdraw=lambda amount: None,
            before_withdraw=lambda amount, assessed_by: seen.append(
                assessed_by
            ),
        )
        processor = make_processor()
        tx = Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("1000"),
            sender=account,
        )
        processor.process(tx)
        assert tx.status.value == "failed"

        with pytest.raises(InsufficientFundsError):
            account.withdraw(Decimal("1000"))
        # both calls reached the hook; the second (direct) one carries
        # no assessed_by token, proving it was not left over from the
        # first (processor-driven) call after that call raised
        assert seen[-1] is None

    def test_shared_risk_analyzer_is_assessed_only_once(
        self, account: BankAccount, other_account: BankAccount
    ):
        # When the sender account was opened through a Bank whose
        # risk_analyzer is the SAME instance the processor uses (the
        # configuration demos/day6_demo.py and day7_demo.py wire up),
        # one processed transaction must record exactly one operation
        # in the analyzer's frequency history - not two.
        risk_analyzer = RiskAnalyzer(clock=lambda: DAY_TIME)
        bank = Bank(
            name="X", clock=lambda: DAY_TIME, risk_analyzer=risk_analyzer
        )
        client = bank.add_client(
            full_name="Anna",
            birth_date=date(1990, 1, 1),
            phone="+79990000001",
            password="secret123",
        )
        acc = bank.open_account(
            client.client_id, initial_balance=Decimal("1000")
        )
        other = bank.open_account(
            client.client_id, initial_balance=Decimal("0")
        )
        processor = TransactionProcessor(
            risk_analyzer=risk_analyzer, clock=lambda: DAY_TIME
        )
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("10"),
            sender=acc,
            receiver=other,
        )
        processor.process(tx)
        assert tx.status.value == "completed"
        assert len(risk_analyzer._recent_operations[acc.account_id]) == 1

    def test_different_processor_analyzer_cannot_bypass_bank_policy(
        self, account: BankAccount, other_account: BankAccount
    ):
        # Regression test: a processor configured with a different (or
        # default) risk_analyzer than the bank's must NOT silently
        # skip the bank's own, stricter policy. Direct withdrawal of
        # 60 is blocked by the bank's strict thresholds; a transfer of
        # the same amount through an independently-configured
        # processor must be blocked too, not silently let through.
        strict_analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("50"),
            frequent_operations_threshold=1,
            clock=lambda: DAY_TIME,
        )
        bank = Bank(
            name="X", clock=lambda: DAY_TIME, risk_analyzer=strict_analyzer
        )
        client = bank.add_client(
            full_name="Anna",
            birth_date=date(1990, 1, 1),
            phone="+79990000001",
            password="secret123",
        )
        acc = bank.open_account(
            client.client_id, initial_balance=Decimal("1000")
        )
        other = bank.open_account(
            client.client_id, initial_balance=Decimal("0")
        )

        processor = TransactionProcessor(clock=lambda: DAY_TIME)
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("60"),
            sender=acc,
            receiver=other,
        )
        processor.process(tx)
        assert tx.status.value == "failed"
        assert "blocked by risk analysis" in tx.failure_reason
        assert acc.balance == Decimal("1000")
        assert other.balance == Decimal("0")


class TestAuditLogIntegration:
    def test_logs_one_entry_per_processed_transaction(
        self, account: BankAccount, other_account: BankAccount
    ):
        audit_log = AuditLog(clock=lambda: DAY_TIME)
        processor = make_processor(audit_log=audit_log)
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("10"),
            sender=account,
            receiver=other_account,
        )
        processor.process(tx)
        assert len(audit_log.entries) == 1
        entry = audit_log.entries[0]
        assert entry.transaction_id == tx.transaction_id
        assert entry.account_id == account.account_id
        assert entry.client == account.owner

    def test_blocked_transaction_logged_as_critical(
        self, account: BankAccount, other_account: BankAccount
    ):
        audit_log = AuditLog(clock=lambda: DAY_TIME)
        risk_analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("50"), clock=lambda: DAY_TIME
        )
        processor = make_processor(
            risk_analyzer=risk_analyzer, audit_log=audit_log
        )
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("60"),
            sender=account,
            receiver=other_account,
        )
        processor.process(tx)
        assert audit_log.entries[0].severity == AuditSeverity.CRITICAL

    def test_medium_risk_completed_transaction_logged_as_warning(
        self, account: BankAccount, other_account: BankAccount
    ):
        audit_log = AuditLog(clock=lambda: DAY_TIME)
        risk_analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("1000000"), clock=lambda: DAY_TIME
        )
        processor = make_processor(
            risk_analyzer=risk_analyzer, audit_log=audit_log
        )
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("10"),
            sender=account,
            receiver=other_account,
        )
        processor.process(tx)
        assert audit_log.entries[0].severity == AuditSeverity.WARNING

    def test_low_risk_completed_transaction_logged_as_info(
        self, account: BankAccount, other_account: BankAccount
    ):
        audit_log = AuditLog(clock=lambda: DAY_TIME)
        risk_analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("1000000"), clock=lambda: DAY_TIME
        )
        processor = make_processor(
            risk_analyzer=risk_analyzer, audit_log=audit_log
        )
        # prime the recipient as known first so the real assertion
        # below has zero triggered risk factors
        processor.process(
            Transaction(
                type=TransactionType.TRANSFER,
                amount=Decimal("1"),
                sender=account,
                receiver=other_account,
            )
        )
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("1"),
            sender=account,
            receiver=other_account,
        )
        processor.process(tx)
        assert audit_log.entries[1].severity == AuditSeverity.INFO

    def test_non_risk_failure_logged_as_warning(self, account: BankAccount):
        audit_log = AuditLog(clock=lambda: DAY_TIME)
        processor = make_processor(audit_log=audit_log)
        tx = Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("1000"),
            sender=account,
        )
        processor.process(tx)
        assert audit_log.entries[0].severity == AuditSeverity.WARNING

    def test_no_audit_log_preserves_default_behavior(
        self, account: BankAccount
    ):
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        make_processor().process(tx)
        assert tx.status.value == "completed"

    def test_audit_write_failure_does_not_crash_a_completed_transaction(
        self, account: BankAccount, tmp_path
    ):
        # A directory, not a file: AuditLog._append_to_file's open()
        # will raise IsADirectoryError. The transaction has already
        # completed by the time _log_outcome runs, so that failure
        # must be swallowed rather than propagated out of process().
        broken_path = tmp_path / "not_a_file"
        broken_path.mkdir()
        audit_log = AuditLog(file_path=broken_path, clock=lambda: DAY_TIME)
        processor = make_processor(audit_log=audit_log)
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=account,
        )
        processor.process(tx)
        assert tx.status.value == "completed"
        assert account.balance == Decimal("110")

    def test_plain_failure_excluded_from_suspicious_report(
        self, account: BankAccount
    ):
        # Regression test: an ordinary insufficient-funds failure
        # (no RiskAnalyzer configured, so zero risk factors) must
        # not show up as a "suspicious operation" just because it
        # failed and got WARNING severity.
        audit_log = AuditLog(clock=lambda: DAY_TIME)
        processor = make_processor(audit_log=audit_log)
        tx = Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("1000"),
            sender=account,
        )
        processor.process(tx)
        assert tx.status.value == "failed"
        assert audit_log.suspicious_operations_report() == []

    def test_plain_failure_counted_in_error_statistics(
        self, account: BankAccount
    ):
        audit_log = AuditLog(clock=lambda: DAY_TIME)
        processor = make_processor(audit_log=audit_log)
        tx = Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("1000"),
            sender=account,
        )
        processor.process(tx)
        stats = audit_log.error_statistics()
        assert stats["total"] == 1
        assert stats["by_event"] == {"transaction_failed": 1}

    def test_successful_transaction_excluded_from_error_statistics(
        self, account: BankAccount, other_account: BankAccount
    ):
        audit_log = AuditLog(clock=lambda: DAY_TIME)
        risk_analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("1000000"), clock=lambda: DAY_TIME
        )
        processor = make_processor(
            risk_analyzer=risk_analyzer, audit_log=audit_log
        )
        tx = Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("10"),
            sender=account,
            receiver=other_account,
        )
        processor.process(tx)
        assert tx.status.value == "completed"
        # MEDIUM risk (new_recipient), so it belongs in the
        # suspicious report, but it succeeded so it must not appear
        # in error_statistics().
        assert len(audit_log.suspicious_operations_report()) == 1
        assert audit_log.error_statistics()["total"] == 0
