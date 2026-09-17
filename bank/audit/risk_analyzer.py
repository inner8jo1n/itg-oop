from collections.abc import Callable
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from bank.enums import RiskLevel
from bank.exceptions import InvalidOperationError

if TYPE_CHECKING:
    from bank.transactions.transaction import Transaction

LARGE_AMOUNT = "large_amount"
FREQUENT_OPERATIONS = "frequent_operations"
NEW_RECIPIENT = "new_recipient"
NIGHT_OPERATION = "night_operation"


class RiskAssessment:
    """
    Outcome of a single RiskAnalyzer.assess() call: an overall risk
    level plus the specific reasons that triggered it.
    """

    def __init__(self, level: RiskLevel, reasons: list[str]):
        """
        Create a risk assessment.

        :param level: overall risk level
        :param reasons: risk factor tags that were triggered
        """
        self._level = level
        self._reasons = list(reasons)

    @property
    def level(self) -> RiskLevel:
        """
        Get the overall risk level.

        :return: risk level
        """
        return self._level

    @property
    def reasons(self) -> list[str]:
        """
        Get a copy of the triggered risk factor tags.

        :return: list of reason tags
        """
        return list(self._reasons)

    def __str__(self) -> str:
        """
        Build a human-readable representation of the assessment.

        :return: string with risk level and triggered reasons
        """
        reasons_text = ", ".join(self._reasons) if self._reasons else "none"
        return f"Risk: {self._level.value} (reasons: {reasons_text})"


class RiskAnalyzer:
    """
    Flags suspicious operations by checking a Transaction against
    four independent risk factors: an unusually large amount,
    frequent operations by the same account in a short window, a
    transfer to a recipient never used before by that sender, and
    operations happening during night hours. The overall risk level
    is derived from how many of these factors triggered.
    """

    def __init__(
        self,
        large_amount_threshold: Decimal = Decimal("1000000"),
        frequent_operations_threshold: int = 3,
        frequent_operations_window: timedelta = timedelta(minutes=5),
        night_start: time = time(0, 0),
        night_end: time = time(5, 0),
        clock: Callable[[], datetime] = datetime.now,
    ):
        """
        Create a risk analyzer.

        :param large_amount_threshold: amount at or above which a
            transaction is flagged as a large amount
        :param frequent_operations_threshold: number of operations
            by the same account within `frequent_operations_window`
            (including the one being assessed) that triggers the
            frequent-operations flag
        :param frequent_operations_window: how far back to look when
            counting an account's recent operations
        :param night_start: start of the night window (inclusive)
        :param night_end: end of the night window (exclusive)
        :param clock: callable returning the current datetime, used
            to timestamp and window operations
        """
        if large_amount_threshold <= 0:
            raise InvalidOperationError(
                "large_amount_threshold must be positive, got "
                f"{large_amount_threshold!r}"
            )
        if (
            not isinstance(frequent_operations_threshold, int)
            or isinstance(frequent_operations_threshold, bool)
            or frequent_operations_threshold < 1
        ):
            raise InvalidOperationError(
                "frequent_operations_threshold must be a positive "
                f"int, got {frequent_operations_threshold!r}"
            )
        if frequent_operations_window <= timedelta(0):
            raise InvalidOperationError(
                "frequent_operations_window must be positive, got "
                f"{frequent_operations_window!r}"
            )
        if not isinstance(night_start, time) or not isinstance(
            night_end, time
        ):
            raise InvalidOperationError(
                "night_start and night_end must be time instances"
            )
        self._large_amount_threshold = large_amount_threshold
        self._frequent_operations_threshold = frequent_operations_threshold
        self._frequent_operations_window = frequent_operations_window
        self._night_start = night_start
        self._night_end = night_end
        self._clock = clock
        self._recent_operations: dict[str, list[datetime]] = {}
        self._known_recipients: dict[str, set[str]] = {}

    @staticmethod
    def _actor_account_id(transaction: "Transaction") -> str | None:
        """
        Get the account id operation frequency should be tracked
        under: the sender if there is one, otherwise the receiver.

        :param transaction: transaction to inspect
        :return: account id, or None if the transaction has neither
        """
        if transaction.sender is not None:
            return transaction.sender.account_id
        if transaction.receiver is not None:
            return transaction.receiver.account_id
        return None

    def _is_large_amount(self, transaction: "Transaction") -> bool:
        """
        Check whether the transaction amount meets the large-amount
        threshold.

        :param transaction: transaction to check
        :return: True if flagged as a large amount
        """
        return transaction.amount >= self._large_amount_threshold

    def _is_frequent(self, actor_id: str | None, now: datetime) -> bool:
        """
        Check whether the actor account has performed enough recent
        operations, including the one being assessed, to be flagged
        as frequent.

        :param actor_id: account id to check history for
        :param now: current time, used to compute the lookback window
        :return: True if flagged as frequent operations
        """
        if actor_id is None:
            return False
        window_start = now - self._frequent_operations_window
        recent = [
            ts
            for ts in self._recent_operations.get(actor_id, ())
            if ts >= window_start
        ]
        return len(recent) + 1 >= self._frequent_operations_threshold

    def _is_new_recipient(self, transaction: "Transaction") -> bool:
        """
        Check whether the transaction's receiver has never received
        funds from this sender before.

        :param transaction: transaction to check
        :return: True if flagged as a transfer to a new recipient
        """
        if transaction.sender is None or transaction.receiver is None:
            return False
        known = self._known_recipients.get(
            transaction.sender.account_id, set()
        )
        return transaction.receiver.account_id not in known

    def _is_night_operation(self, now: datetime) -> bool:
        """
        Check whether the given time falls within the night window.

        :param now: time to check
        :return: True if flagged as a night operation
        """
        current_time = now.time()
        if self._night_start <= self._night_end:
            return self._night_start <= current_time < self._night_end
        return (
            current_time >= self._night_start or current_time < self._night_end
        )

    def assess(self, transaction: "Transaction") -> RiskAssessment:
        """
        Evaluate a transaction against all four risk factors and
        record its timestamp into this analyzer's frequency history,
        so future frequency checks account for it. This does NOT
        mark the receiver as a known recipient — that only happens
        once the transaction actually completes, via
        record_completed(). Learning trust from a merely-attempted
        transfer (including one this very call blocks) would let a
        HIGH-risk block be defeated by simply resubmitting the same
        transfer, since new_recipient would no longer fire the
        second time. Each transaction should be assessed at most
        once.

        :param transaction: transaction to assess
        :return: the resulting risk assessment
        """
        from bank.transactions.transaction import Transaction as _Transaction

        if not isinstance(transaction, _Transaction):
            raise InvalidOperationError(
                f"Expected a Transaction, got {transaction!r}"
            )
        now = self._clock()
        actor_id = self._actor_account_id(transaction)

        reasons = []
        if self._is_large_amount(transaction):
            reasons.append(LARGE_AMOUNT)
        if self._is_frequent(actor_id, now):
            reasons.append(FREQUENT_OPERATIONS)
        if self._is_new_recipient(transaction):
            reasons.append(NEW_RECIPIENT)
        if self._is_night_operation(now):
            reasons.append(NIGHT_OPERATION)

        self._record_frequency(actor_id, now)

        return RiskAssessment(
            level=self._level_for(len(reasons)), reasons=reasons
        )

    def record_completed(self, transaction: "Transaction") -> None:
        """
        Mark the transaction's receiver as a known recipient of its
        sender. Call this only once a transfer has actually
        completed successfully (never from assess() itself), so a
        blocked or failed attempt can never make its recipient look
        trusted on a later assessment. No-op for transaction types
        without both a sender and a receiver.

        :param transaction: transaction that just completed
        :return: None
        """
        if transaction.sender is not None and transaction.receiver is not None:
            known = self._known_recipients.setdefault(
                transaction.sender.account_id, set()
            )
            known.add(transaction.receiver.account_id)

    def _record_frequency(self, actor_id: str | None, now: datetime) -> None:
        """
        Append this operation's timestamp to the actor's recent-
        operations history, trimmed to the current window. Applied
        to every assessed attempt regardless of outcome, since a
        burst of attempts is itself a meaningful signal even when
        individual attempts are blocked or fail.

        :param actor_id: account id to record operation frequency
            under, as returned by _actor_account_id
        :param now: time the transaction was assessed
        :return: None
        """
        if actor_id is None:
            return
        window_start = now - self._frequent_operations_window
        history = [
            ts
            for ts in self._recent_operations.get(actor_id, ())
            if ts >= window_start
        ]
        history.append(now)
        self._recent_operations[actor_id] = history

    @staticmethod
    def _level_for(triggered_count: int) -> RiskLevel:
        """
        Map the number of triggered risk factors to an overall
        risk level.

        :param triggered_count: number of risk factors triggered
        :return: LOW for none, MEDIUM for exactly one, HIGH for two
            or more
        """
        if triggered_count >= 2:
            return RiskLevel.HIGH
        if triggered_count == 1:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW
