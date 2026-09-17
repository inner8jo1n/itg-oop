from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest

from bank.accounts.bank_account import BankAccount
from bank.audit.risk_analyzer import (
    FREQUENT_OPERATIONS,
    LARGE_AMOUNT,
    NEW_RECIPIENT,
    NIGHT_OPERATION,
    RiskAnalyzer,
)
from bank.enums import RiskLevel, TransactionType
from bank.exceptions import InvalidOperationError
from bank.transactions.transaction import Transaction

DAY_TIME = datetime(2024, 1, 1, 12, 0, 0)
NIGHT_TIME = datetime(2024, 1, 1, 2, 0, 0)


def make_transfer(sender, receiver, amount="10") -> Transaction:
    return Transaction(
        type=TransactionType.TRANSFER,
        amount=Decimal(amount),
        sender=sender,
        receiver=receiver,
    )


class TestConstruction:
    def test_rejects_non_positive_large_amount_threshold(self):
        with pytest.raises(InvalidOperationError):
            RiskAnalyzer(large_amount_threshold=Decimal("0"))

    def test_rejects_non_positive_frequent_operations_threshold(self):
        with pytest.raises(InvalidOperationError):
            RiskAnalyzer(frequent_operations_threshold=0)

    def test_rejects_non_int_frequent_operations_threshold(self):
        with pytest.raises(InvalidOperationError):
            RiskAnalyzer(frequent_operations_threshold="3")

    def test_rejects_bool_frequent_operations_threshold(self):
        with pytest.raises(InvalidOperationError):
            RiskAnalyzer(frequent_operations_threshold=True)

    def test_rejects_non_positive_frequent_operations_window(self):
        with pytest.raises(InvalidOperationError):
            RiskAnalyzer(frequent_operations_window=timedelta(0))

    def test_rejects_non_time_night_bounds(self):
        with pytest.raises(InvalidOperationError):
            RiskAnalyzer(night_start="00:00")


class TestAssessRejectsNonTransaction:
    def test_rejects_non_transaction(self):
        with pytest.raises(InvalidOperationError):
            RiskAnalyzer().assess(object())


class TestLargeAmount:
    def test_flags_amount_at_threshold(self):
        analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("1000"), clock=lambda: DAY_TIME
        )
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        receiver = BankAccount(owner="B")
        tx = make_transfer(sender, receiver, "1000")
        assessment = analyzer.assess(tx)
        assert LARGE_AMOUNT in assessment.reasons

    def test_does_not_flag_amount_below_threshold(self):
        analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("1000"), clock=lambda: DAY_TIME
        )
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        receiver = BankAccount(owner="B")
        tx = make_transfer(sender, receiver, "999")
        assessment = analyzer.assess(tx)
        assert LARGE_AMOUNT not in assessment.reasons


class TestFrequentOperations:
    def test_first_two_operations_are_not_frequent(self):
        analyzer = RiskAnalyzer(
            frequent_operations_threshold=3, clock=lambda: DAY_TIME
        )
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        r1 = BankAccount(owner="B")
        r2 = BankAccount(owner="C")
        assert (
            FREQUENT_OPERATIONS
            not in analyzer.assess(make_transfer(sender, r1)).reasons
        )
        assert (
            FREQUENT_OPERATIONS
            not in analyzer.assess(make_transfer(sender, r2)).reasons
        )

    def test_third_operation_within_window_is_frequent(self):
        analyzer = RiskAnalyzer(
            frequent_operations_threshold=3, clock=lambda: DAY_TIME
        )
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        recipients = [BankAccount(owner=f"R{i}") for i in range(3)]
        for recipient in recipients[:2]:
            analyzer.assess(make_transfer(sender, recipient))
        assessment = analyzer.assess(make_transfer(sender, recipients[2]))
        assert FREQUENT_OPERATIONS in assessment.reasons

    def test_operations_outside_window_do_not_count(self):
        clock = {"now": DAY_TIME}
        analyzer = RiskAnalyzer(
            frequent_operations_threshold=3,
            frequent_operations_window=timedelta(minutes=5),
            clock=lambda: clock["now"],
        )
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        recipients = [BankAccount(owner=f"R{i}") for i in range(3)]
        analyzer.assess(make_transfer(sender, recipients[0]))
        clock["now"] = DAY_TIME + timedelta(minutes=1)
        analyzer.assess(make_transfer(sender, recipients[1]))
        clock["now"] = DAY_TIME + timedelta(minutes=10)
        assessment = analyzer.assess(make_transfer(sender, recipients[2]))
        assert FREQUENT_OPERATIONS not in assessment.reasons

    def test_deposit_frequency_tracked_by_receiver(self):
        analyzer = RiskAnalyzer(
            frequent_operations_threshold=2, clock=lambda: DAY_TIME
        )
        receiver = BankAccount(owner="A")
        first = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=receiver,
        )
        second = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=receiver,
        )
        analyzer.assess(first)
        assessment = analyzer.assess(second)
        assert FREQUENT_OPERATIONS in assessment.reasons


class TestNewRecipient:
    def test_flags_first_transfer_to_a_receiver(self):
        analyzer = RiskAnalyzer(clock=lambda: DAY_TIME)
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        receiver = BankAccount(owner="B")
        assessment = analyzer.assess(make_transfer(sender, receiver))
        assert NEW_RECIPIENT in assessment.reasons

    def test_does_not_flag_repeat_transfer_once_first_one_completed(self):
        analyzer = RiskAnalyzer(clock=lambda: DAY_TIME)
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        receiver = BankAccount(owner="B")
        first = make_transfer(sender, receiver)
        analyzer.assess(first)
        analyzer.record_completed(first)
        assessment = analyzer.assess(make_transfer(sender, receiver))
        assert NEW_RECIPIENT not in assessment.reasons

    def test_still_flags_repeat_assess_without_completion(self):
        # assess() alone must never grant trust — only
        # record_completed() does. Otherwise a blocked or failed
        # attempt would make its recipient look "known" on a retry,
        # defeating the HIGH-risk block via simple resubmission.
        analyzer = RiskAnalyzer(clock=lambda: DAY_TIME)
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        receiver = BankAccount(owner="B")
        analyzer.assess(make_transfer(sender, receiver))
        assessment = analyzer.assess(make_transfer(sender, receiver))
        assert NEW_RECIPIENT in assessment.reasons

    def test_does_not_apply_to_withdrawal(self):
        analyzer = RiskAnalyzer(clock=lambda: DAY_TIME)
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        tx = Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("10"),
            sender=sender,
        )
        assessment = analyzer.assess(tx)
        assert NEW_RECIPIENT not in assessment.reasons

    def test_does_not_apply_to_deposit(self):
        analyzer = RiskAnalyzer(clock=lambda: DAY_TIME)
        receiver = BankAccount(owner="A")
        tx = Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("10"),
            receiver=receiver,
        )
        assessment = analyzer.assess(tx)
        assert NEW_RECIPIENT not in assessment.reasons

    def test_record_completed_is_a_noop_for_deposit_and_withdrawal(self):
        analyzer = RiskAnalyzer(clock=lambda: DAY_TIME)
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        withdrawal = Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("10"),
            sender=sender,
        )
        # must not raise, and must not create any known-recipient
        # entry for a transaction type that has no receiver
        analyzer.record_completed(withdrawal)


class TestNightOperation:
    def test_flags_operation_within_default_night_window(self):
        analyzer = RiskAnalyzer(clock=lambda: NIGHT_TIME)
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        receiver = BankAccount(owner="B")
        assessment = analyzer.assess(make_transfer(sender, receiver))
        assert NIGHT_OPERATION in assessment.reasons

    def test_does_not_flag_daytime_operation(self):
        analyzer = RiskAnalyzer(clock=lambda: DAY_TIME)
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        receiver = BankAccount(owner="B")
        assessment = analyzer.assess(make_transfer(sender, receiver))
        assert NIGHT_OPERATION not in assessment.reasons

    def test_start_boundary_is_inclusive(self):
        analyzer = RiskAnalyzer(clock=lambda: datetime(2024, 1, 1, 0, 0, 0))
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        receiver = BankAccount(owner="B")
        assessment = analyzer.assess(make_transfer(sender, receiver))
        assert NIGHT_OPERATION in assessment.reasons

    def test_end_boundary_is_exclusive(self):
        analyzer = RiskAnalyzer(clock=lambda: datetime(2024, 1, 1, 5, 0, 0))
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        receiver = BankAccount(owner="B")
        assessment = analyzer.assess(make_transfer(sender, receiver))
        assert NIGHT_OPERATION not in assessment.reasons

    def test_wrap_around_window_crossing_midnight(self):
        analyzer = RiskAnalyzer(
            night_start=time(22, 0),
            night_end=time(6, 0),
            clock=lambda: datetime(2024, 1, 1, 23, 0, 0),
        )
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        receiver = BankAccount(owner="B")
        assessment = analyzer.assess(make_transfer(sender, receiver))
        assert NIGHT_OPERATION in assessment.reasons

    def test_wrap_around_window_excludes_daytime(self):
        analyzer = RiskAnalyzer(
            night_start=time(22, 0),
            night_end=time(6, 0),
            clock=lambda: datetime(2024, 1, 1, 12, 0, 0),
        )
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        receiver = BankAccount(owner="B")
        assessment = analyzer.assess(make_transfer(sender, receiver))
        assert NIGHT_OPERATION not in assessment.reasons


class TestRiskLevelMapping:
    def test_zero_factors_is_low(self):
        analyzer = RiskAnalyzer(clock=lambda: DAY_TIME)
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        receiver = BankAccount(owner="B")
        first = make_transfer(sender, receiver)
        analyzer.assess(first)
        analyzer.record_completed(first)
        assessment = analyzer.assess(make_transfer(sender, receiver, "1"))
        assert assessment.level == RiskLevel.LOW
        assert assessment.reasons == []

    def test_one_factor_is_medium(self):
        analyzer = RiskAnalyzer(clock=lambda: DAY_TIME)
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        receiver = BankAccount(owner="B")
        assessment = analyzer.assess(make_transfer(sender, receiver))
        assert assessment.level == RiskLevel.MEDIUM
        assert len(assessment.reasons) == 1

    def test_two_or_more_factors_is_high(self):
        analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("1000"), clock=lambda: NIGHT_TIME
        )
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        receiver = BankAccount(owner="B")
        assessment = analyzer.assess(make_transfer(sender, receiver, "5000"))
        assert assessment.level == RiskLevel.HIGH
        assert len(assessment.reasons) >= 2


class TestRiskAssessmentString:
    def test_str_lists_reasons(self):
        analyzer = RiskAnalyzer(clock=lambda: DAY_TIME)
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        receiver = BankAccount(owner="B")
        assessment = analyzer.assess(make_transfer(sender, receiver))
        assert "medium" in str(assessment)
        assert NEW_RECIPIENT in str(assessment)

    def test_str_shows_none_when_no_reasons(self):
        analyzer = RiskAnalyzer(clock=lambda: DAY_TIME)
        sender = BankAccount(owner="A", initial_balance=Decimal("100000"))
        receiver = BankAccount(owner="B")
        first = make_transfer(sender, receiver)
        analyzer.assess(first)
        analyzer.record_completed(first)
        assessment = analyzer.assess(make_transfer(sender, receiver, "1"))
        assert "none" in str(assessment)
