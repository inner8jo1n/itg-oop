import contextlib
from datetime import date, datetime
from decimal import Decimal

import pytest

from bank.accounts.premium_account import PremiumAccount
from bank.accounts.savings_account import SavingsAccount
from bank.audit.audit_log import AuditLog
from bank.audit.risk_analyzer import RiskAnalyzer
from bank.bank import Bank
from bank.client import Client
from bank.enums import AccountStatus, AuditSeverity, Currency
from bank.exceptions import (
    AccountNotFoundError,
    AuthenticationError,
    ClientBlockedError,
    ClientNotFoundError,
    InvalidOperationError,
    OperationNotAllowedError,
    RiskBlockedError,
)

DAY_TIME = datetime(2024, 1, 1, 12, 0, 0)
NIGHT_TIME = datetime(2024, 1, 1, 2, 0, 0)


class TestAddClient:
    def test_registers_client(self, bank: Bank, adult_birth_date: date):
        client = bank.add_client(
            full_name="Anna Volkova",
            birth_date=adult_birth_date,
            phone="+79990000001",
            password="secret123",
        )
        assert client.client_id in bank.clients

    def test_rejects_at_night(self, adult_birth_date: date):
        night_bank = Bank(name="Night Bank", clock=lambda: NIGHT_TIME)
        with pytest.raises(OperationNotAllowedError):
            night_bank.add_client(
                full_name="Anna Volkova",
                birth_date=adult_birth_date,
                phone="+79990000001",
                password="secret123",
            )

    def test_propagates_client_validation_errors(self, bank: Bank):
        underage_birth_date = date.today().replace(year=date.today().year - 10)
        with pytest.raises(InvalidOperationError):
            bank.add_client(
                full_name="Young Client",
                birth_date=underage_birth_date,
                phone="+79990000005",
                password="secret123",
            )


class TestOpenAccount:
    def test_opens_default_bank_account(self, bank: Bank, client: Client):
        account = bank.open_account(
            client.client_id, initial_balance=Decimal("500")
        )
        assert account.account_id in bank.accounts
        assert account.account_id in client.account_ids
        assert account.owner == client.full_name

    def test_opens_typed_account_with_extra_kwargs(
        self, bank: Bank, client: Client
    ):
        account = bank.open_account(
            client.client_id,
            account_cls=SavingsAccount,
            initial_balance=Decimal("1000"),
            min_balance=Decimal("100"),
            monthly_interest_rate=Decimal("0.02"),
        )
        assert isinstance(account, SavingsAccount)
        assert account.min_balance == Decimal("100")

    def test_rejects_unknown_client(self, bank: Bank):
        with pytest.raises(ClientNotFoundError):
            bank.open_account("does-not-exist")

    def test_rejects_non_bank_account_class(self, bank: Bank, client: Client):
        with pytest.raises(InvalidOperationError):
            bank.open_account(client.client_id, account_cls=object)

    def test_rejects_at_night(self, bank: Bank, client: Client):
        bank._clock = lambda: NIGHT_TIME
        with pytest.raises(OperationNotAllowedError):
            bank.open_account(client.client_id)

    def test_failed_construction_leaves_nothing_registered(
        self, bank: Bank, client: Client
    ):
        with pytest.raises(InvalidOperationError):
            bank.open_account(
                client.client_id,
                account_cls=SavingsAccount,
                initial_balance=Decimal("50"),
                min_balance=Decimal("100"),
            )
        assert bank.accounts == {}
        assert client.account_ids == []


class TestAccountLifecycle:
    def test_freeze_and_unfreeze(self, bank: Bank, client: Client):
        account = bank.open_account(client.client_id)
        bank.freeze_account(account.account_id)
        assert account.status == AccountStatus.FROZEN
        bank.unfreeze_account(account.account_id)
        assert account.status == AccountStatus.ACTIVE

    def test_close(self, bank: Bank, client: Client):
        account = bank.open_account(client.client_id)
        bank.close_account(account.account_id)
        assert account.status == AccountStatus.CLOSED

    def test_freeze_rejects_unknown_account(self, bank: Bank):
        with pytest.raises(AccountNotFoundError):
            bank.freeze_account("does-not-exist")

    def test_close_rejects_unknown_account(self, bank: Bank):
        with pytest.raises(AccountNotFoundError):
            bank.close_account("does-not-exist")

    def test_unfreeze_rejects_unknown_account(self, bank: Bank):
        with pytest.raises(AccountNotFoundError):
            bank.unfreeze_account("does-not-exist")

    def test_close_rejects_at_night(self, bank: Bank, client: Client):
        account = bank.open_account(client.client_id)
        bank._clock = lambda: NIGHT_TIME
        with pytest.raises(OperationNotAllowedError):
            bank.close_account(account.account_id)

    def test_freeze_rejects_at_night(self, bank: Bank, client: Client):
        account = bank.open_account(client.client_id)
        bank._clock = lambda: NIGHT_TIME
        with pytest.raises(OperationNotAllowedError):
            bank.freeze_account(account.account_id)

    def test_unfreeze_rejects_at_night(self, bank: Bank, client: Client):
        account = bank.open_account(client.client_id)
        bank.freeze_account(account.account_id)
        bank._clock = lambda: NIGHT_TIME
        with pytest.raises(OperationNotAllowedError):
            bank.unfreeze_account(account.account_id)


class TestAuthenticateClient:
    def test_succeeds_with_correct_password(self, bank: Bank, client: Client):
        assert bank.authenticate_client(client.client_id, "secret123") is True

    def test_fails_with_wrong_password(self, bank: Bank, client: Client):
        with pytest.raises(AuthenticationError):
            bank.authenticate_client(client.client_id, "wrong")
        assert client.failed_login_attempts == 1

    def test_success_resets_failed_attempts(self, bank: Bank, client: Client):
        with pytest.raises(AuthenticationError):
            bank.authenticate_client(client.client_id, "wrong")
        bank.authenticate_client(client.client_id, "secret123")
        assert client.failed_login_attempts == 0

    def test_blocks_after_three_failed_attempts(
        self, bank: Bank, client: Client
    ):
        for _ in range(2):
            with pytest.raises(AuthenticationError):
                bank.authenticate_client(client.client_id, "wrong")
        with pytest.raises(ClientBlockedError):
            bank.authenticate_client(client.client_id, "wrong")
        assert client.is_blocked

    def test_blocked_client_rejected_even_with_correct_password(
        self, bank: Bank, client: Client
    ):
        for _ in range(3):
            with contextlib.suppress(AuthenticationError, ClientBlockedError):
                bank.authenticate_client(client.client_id, "wrong")
        with pytest.raises(ClientBlockedError):
            bank.authenticate_client(client.client_id, "secret123")

    def test_rejects_unknown_client(self, bank: Bank):
        with pytest.raises(ClientNotFoundError):
            bank.authenticate_client("does-not-exist", "secret123")

    def test_rejects_and_flags_suspicious_at_night(
        self, bank: Bank, client: Client
    ):
        bank._clock = lambda: NIGHT_TIME
        with pytest.raises(OperationNotAllowedError):
            bank.authenticate_client(client.client_id, "secret123")
        assert client.is_suspicious


class TestNightRestrictionBoundary:
    def test_exactly_midnight_is_restricted(self, adult_birth_date: date):
        bank = Bank(
            name="Boundary Bank",
            clock=lambda: datetime(2024, 1, 1, 0, 0, 0),
        )
        with pytest.raises(OperationNotAllowedError):
            bank.add_client(
                full_name="Anna Volkova",
                birth_date=adult_birth_date,
                phone="+79990000001",
                password="secret123",
            )

    def test_exactly_five_am_is_allowed(self, adult_birth_date: date):
        bank = Bank(
            name="Boundary Bank",
            clock=lambda: datetime(2024, 1, 1, 5, 0, 0),
        )
        client = bank.add_client(
            full_name="Anna Volkova",
            birth_date=adult_birth_date,
            phone="+79990000001",
            password="secret123",
        )
        assert client.client_id in bank.clients

    def test_one_second_before_five_am_is_restricted(
        self, adult_birth_date: date
    ):
        bank = Bank(
            name="Boundary Bank",
            clock=lambda: datetime(2024, 1, 1, 4, 59, 59),
        )
        with pytest.raises(OperationNotAllowedError):
            bank.add_client(
                full_name="Anna Volkova",
                birth_date=adult_birth_date,
                phone="+79990000001",
                password="secret123",
            )


class TestWithdrawFromAccount:
    def test_normal_withdrawal_is_not_suspicious(
        self, bank: Bank, client: Client
    ):
        account = bank.open_account(
            client.client_id, initial_balance=Decimal("1000")
        )
        bank.withdraw_from_account(account.account_id, Decimal("100"))
        assert account.balance == Decimal("900")
        assert client.is_suspicious is False

    def test_large_withdrawal_flags_suspicious(
        self, bank: Bank, client: Client
    ):
        account = bank.open_account(
            client.client_id, initial_balance=Decimal("2000000")
        )
        bank.withdraw_from_account(account.account_id, Decimal("1500000"))
        assert client.is_suspicious is True

    def test_rejects_unknown_account(self, bank: Bank):
        with pytest.raises(AccountNotFoundError):
            bank.withdraw_from_account("does-not-exist", Decimal("10"))

    def test_exactly_at_threshold_is_not_suspicious(
        self, bank: Bank, client: Client
    ):
        account = bank.open_account(
            client.client_id, initial_balance=Decimal("2000000")
        )
        bank.withdraw_from_account(account.account_id, Decimal("1000000"))
        assert client.is_suspicious is False

    def test_custom_threshold_is_honored(self, adult_birth_date: date):
        low_threshold_bank = Bank(
            name="Low Threshold Bank",
            clock=lambda: datetime(2024, 1, 1, 12, 0, 0),
            suspicious_withdrawal_threshold=Decimal("100"),
        )
        client = low_threshold_bank.add_client(
            full_name="Petr Sidorov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
        )
        account = low_threshold_bank.open_account(
            client.client_id, initial_balance=Decimal("1000")
        )
        low_threshold_bank.withdraw_from_account(
            account.account_id, Decimal("150")
        )
        assert client.is_suspicious is True

    def test_rejects_and_flags_suspicious_at_night(
        self, bank: Bank, client: Client
    ):
        account = bank.open_account(
            client.client_id, initial_balance=Decimal("1000")
        )
        bank._clock = lambda: NIGHT_TIME
        with pytest.raises(OperationNotAllowedError):
            bank.withdraw_from_account(account.account_id, Decimal("100"))
        assert client.is_suspicious is True


class TestBankRiskAndAuditIntegration:
    """
    Bank.withdraw_from_account can be wired to a RiskAnalyzer and an
    AuditLog: a HIGH-risk withdrawal is blocked with RiskBlockedError
    before the balance is touched, and every withdrawal attempt is
    recorded to the AuditLog when one is configured. Without a
    RiskAnalyzer configured (the default), behavior is unchanged from
    before this feature existed: dangerous withdrawals still only get
    flagged after the fact, never refused.
    """

    @staticmethod
    def _open_account(bank: Bank, adult_birth_date, balance: Decimal):
        client = bank.add_client(
            full_name="Petr Sidorov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
        )
        account = bank.open_account(client.client_id, initial_balance=balance)
        return client, account

    def test_constructor_accepts_risk_analyzer_and_audit_log(self):
        bank = Bank(
            name="X",
            risk_analyzer=RiskAnalyzer(clock=lambda: DAY_TIME),
            audit_log=AuditLog(clock=lambda: DAY_TIME),
        )
        assert bank is not None

    def test_high_risk_withdrawal_is_blocked_before_balance_changes(
        self, adult_birth_date
    ):
        # large_amount (threshold 1000) + night_operation (analyzer
        # clock at 02:00, Bank's own clock stays at noon so the
        # unrelated Day 3 night restriction never interferes here)
        risk_analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("1000"), clock=lambda: NIGHT_TIME
        )
        bank = Bank(
            name="X", clock=lambda: DAY_TIME, risk_analyzer=risk_analyzer
        )
        _, account = self._open_account(
            bank, adult_birth_date, Decimal("100000")
        )
        with pytest.raises(RiskBlockedError):
            bank.withdraw_from_account(account.account_id, Decimal("2000"))
        assert account.balance == Decimal("100000")

    def test_blocked_withdrawal_also_flags_client_suspicious(
        self, adult_birth_date
    ):
        risk_analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("1000"), clock=lambda: NIGHT_TIME
        )
        bank = Bank(
            name="X", clock=lambda: DAY_TIME, risk_analyzer=risk_analyzer
        )
        client, account = self._open_account(
            bank, adult_birth_date, Decimal("100000")
        )
        with pytest.raises(RiskBlockedError):
            bank.withdraw_from_account(account.account_id, Decimal("2000"))
        assert client.is_suspicious is True

    def test_low_risk_withdrawal_still_succeeds(self, adult_birth_date):
        risk_analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("1000000"), clock=lambda: DAY_TIME
        )
        bank = Bank(
            name="X", clock=lambda: DAY_TIME, risk_analyzer=risk_analyzer
        )
        _, account = self._open_account(
            bank, adult_birth_date, Decimal("1000")
        )
        bank.withdraw_from_account(account.account_id, Decimal("100"))
        assert account.balance == Decimal("900")

    def test_audit_log_records_blocked_withdrawal_as_critical(
        self, adult_birth_date
    ):
        risk_analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("1000"), clock=lambda: NIGHT_TIME
        )
        audit_log = AuditLog(clock=lambda: DAY_TIME)
        bank = Bank(
            name="X",
            clock=lambda: DAY_TIME,
            risk_analyzer=risk_analyzer,
            audit_log=audit_log,
        )
        _, account = self._open_account(
            bank, adult_birth_date, Decimal("100000")
        )
        with pytest.raises(RiskBlockedError):
            bank.withdraw_from_account(account.account_id, Decimal("2000"))
        assert len(audit_log.entries) == 1
        assert audit_log.entries[0].severity == AuditSeverity.CRITICAL

    def test_audit_log_records_successful_withdrawal_as_info(
        self, adult_birth_date
    ):
        risk_analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("1000000"), clock=lambda: DAY_TIME
        )
        audit_log = AuditLog(clock=lambda: DAY_TIME)
        bank = Bank(
            name="X",
            clock=lambda: DAY_TIME,
            risk_analyzer=risk_analyzer,
            audit_log=audit_log,
        )
        _, account = self._open_account(
            bank, adult_birth_date, Decimal("1000")
        )
        bank.withdraw_from_account(account.account_id, Decimal("100"))
        assert audit_log.entries[0].severity == AuditSeverity.INFO

    def test_without_risk_analyzer_behavior_is_unchanged(
        self, bank: Bank, client: Client
    ):
        # No RiskAnalyzer configured on this bank (the default `bank`
        # fixture): a large withdrawal still only gets flagged after
        # the fact, exactly as before this feature existed - it is
        # never blocked.
        account = bank.open_account(
            client.client_id, initial_balance=Decimal("100000000")
        )
        bank.withdraw_from_account(account.account_id, Decimal("99000000"))
        assert account.balance == Decimal("1000000")
        assert client.is_suspicious is True

    def test_plain_withdrawal_excluded_from_suspicious_report(
        self, adult_birth_date
    ):
        # No RiskAnalyzer configured: a withdrawal that fails for an
        # ordinary business reason has no risk factors at all and
        # must not appear in the suspicious-operations report.
        audit_log = AuditLog(clock=lambda: DAY_TIME)
        bank = Bank(name="X", clock=lambda: DAY_TIME, audit_log=audit_log)
        _, account = self._open_account(
            bank, adult_birth_date, Decimal("1000")
        )
        bank.withdraw_from_account(account.account_id, Decimal("100"))
        assert audit_log.suspicious_operations_report() == []
        assert audit_log.error_statistics()["total"] == 0

    def test_direct_account_withdraw_is_also_blocked(self, adult_birth_date):
        # Regression test: risk checking must not be bypassable by
        # calling account.withdraw() directly instead of going
        # through Bank.withdraw_from_account(). The check is bound
        # as the account's before_withdraw hook in open_account(),
        # so it fires no matter which entry point is used.
        risk_analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("1000"), clock=lambda: NIGHT_TIME
        )
        bank = Bank(
            name="X", clock=lambda: DAY_TIME, risk_analyzer=risk_analyzer
        )
        client, account = self._open_account(
            bank, adult_birth_date, Decimal("100000")
        )
        with pytest.raises(RiskBlockedError):
            account.withdraw(Decimal("2000"))
        assert account.balance == Decimal("100000")
        assert client.is_suspicious is True

    def test_direct_account_withdraw_still_succeeds_when_low_risk(
        self, adult_birth_date
    ):
        risk_analyzer = RiskAnalyzer(
            large_amount_threshold=Decimal("1000000"), clock=lambda: DAY_TIME
        )
        bank = Bank(
            name="X", clock=lambda: DAY_TIME, risk_analyzer=risk_analyzer
        )
        _, account = self._open_account(
            bank, adult_birth_date, Decimal("1000")
        )
        account.withdraw(Decimal("100"))
        assert account.balance == Decimal("900")


class TestSearchAccounts:
    def test_filters_by_owner_substring(self, bank: Bank, client: Client):
        bank.open_account(client.client_id)
        results = bank.search_accounts(owner="petr")
        assert len(results) == 1

    def test_filters_by_currency(self, bank: Bank, client: Client):
        bank.open_account(client.client_id, currency=Currency.USD)
        bank.open_account(client.client_id, currency=Currency.RUB)
        results = bank.search_accounts(currency=Currency.USD)
        assert len(results) == 1
        assert results[0].currency == Currency.USD

    def test_filters_by_status(self, bank: Bank, client: Client):
        frozen = bank.open_account(client.client_id)
        bank.open_account(client.client_id)
        bank.freeze_account(frozen.account_id)
        results = bank.search_accounts(status=AccountStatus.FROZEN)
        assert results == [frozen]

    def test_filters_by_balance_range(self, bank: Bank, client: Client):
        bank.open_account(client.client_id, initial_balance=Decimal("100"))
        rich = bank.open_account(
            client.client_id, initial_balance=Decimal("5000")
        )
        results = bank.search_accounts(min_balance=Decimal("1000"))
        assert results == [rich]

    def test_filters_by_max_balance(self, bank: Bank, client: Client):
        poor = bank.open_account(
            client.client_id, initial_balance=Decimal("100")
        )
        bank.open_account(client.client_id, initial_balance=Decimal("5000"))
        results = bank.search_accounts(max_balance=Decimal("1000"))
        assert results == [poor]

    def test_combines_multiple_criteria(self, bank: Bank, client: Client):
        target = bank.open_account(
            client.client_id,
            currency=Currency.USD,
            initial_balance=Decimal("500"),
        )
        bank.open_account(
            client.client_id,
            currency=Currency.USD,
            initial_balance=Decimal("5000"),
        )
        bank.open_account(
            client.client_id,
            currency=Currency.RUB,
            initial_balance=Decimal("500"),
        )
        results = bank.search_accounts(
            currency=Currency.USD, max_balance=Decimal("1000")
        )
        assert results == [target]

    def test_returns_empty_list_when_nothing_matches(
        self, bank: Bank, client: Client
    ):
        bank.open_account(client.client_id)
        assert bank.search_accounts(owner="nonexistent") == []

    def test_returns_empty_list_for_empty_registry(self, bank: Bank):
        assert bank.search_accounts() == []

    def test_returns_all_when_no_criteria(self, bank: Bank, client: Client):
        bank.open_account(client.client_id)
        bank.open_account(client.client_id)
        assert len(bank.search_accounts()) == 2


class TestReporting:
    def test_get_total_balance_grouped_by_currency(
        self, bank: Bank, client: Client
    ):
        bank.open_account(
            client.client_id,
            currency=Currency.RUB,
            initial_balance=Decimal("1000"),
        )
        bank.open_account(
            client.client_id,
            currency=Currency.USD,
            initial_balance=Decimal("200"),
        )
        bank.open_account(
            client.client_id,
            currency=Currency.RUB,
            initial_balance=Decimal("500"),
        )
        totals = bank.get_total_balance()
        assert totals[Currency.RUB] == Decimal("1500")
        assert totals[Currency.USD] == Decimal("200")

    def test_get_total_balance_empty_bank(self, bank: Bank):
        assert bank.get_total_balance() == {}

    def test_get_total_balance_includes_negative_overdraft(
        self, bank: Bank, client: Client
    ):
        account = bank.open_account(
            client.client_id,
            account_cls=PremiumAccount,
            currency=Currency.RUB,
            initial_balance=Decimal("100"),
            overdraft_limit=Decimal("200"),
        )
        bank.withdraw_from_account(account.account_id, Decimal("250"))
        totals = bank.get_total_balance()
        assert totals[Currency.RUB] == Decimal("-150")

    def test_get_clients_ranking_sums_multiple_currencies(
        self, bank: Bank, adult_birth_date: date
    ):
        multi_client = bank.add_client(
            full_name="Multi Currency Client",
            birth_date=adult_birth_date,
            phone="+79990000004",
            password="secret123",
        )
        bank.open_account(
            multi_client.client_id,
            currency=Currency.RUB,
            initial_balance=Decimal("100"),
        )
        bank.open_account(
            multi_client.client_id,
            currency=Currency.USD,
            initial_balance=Decimal("100"),
        )
        ranking = bank.get_clients_ranking()
        assert ranking[0][0] is multi_client
        assert ranking[0][1] == Decimal("200")

    def test_get_clients_ranking_includes_client_with_no_accounts(
        self, bank: Bank, adult_birth_date: date
    ):
        empty_client = bank.add_client(
            full_name="No Accounts Client",
            birth_date=adult_birth_date,
            phone="+79990000005",
            password="secret123",
        )
        ranking = bank.get_clients_ranking()
        assert (empty_client, Decimal("0")) in ranking

    def test_get_clients_ranking_handles_tie(
        self, bank: Bank, adult_birth_date: date
    ):
        client_a = bank.add_client(
            full_name="Client A",
            birth_date=adult_birth_date,
            phone="+79990000006",
            password="secret123",
        )
        client_b = bank.add_client(
            full_name="Client B",
            birth_date=adult_birth_date,
            phone="+79990000007",
            password="secret123",
        )
        bank.open_account(client_a.client_id, initial_balance=Decimal("500"))
        bank.open_account(client_b.client_id, initial_balance=Decimal("500"))
        ranking = bank.get_clients_ranking()
        ranked_clients = {client for client, _ in ranking}
        assert ranked_clients == {client_a, client_b}
        assert all(total == Decimal("500") for _, total in ranking)

    def test_get_clients_ranking_sorted_descending(
        self, bank: Bank, adult_birth_date: date
    ):
        poor_client = bank.add_client(
            full_name="Poor Client",
            birth_date=adult_birth_date,
            phone="+79990000002",
            password="secret123",
        )
        rich_client = bank.add_client(
            full_name="Rich Client",
            birth_date=adult_birth_date,
            phone="+79990000003",
            password="secret123",
        )
        bank.open_account(
            poor_client.client_id, initial_balance=Decimal("100")
        )
        bank.open_account(
            rich_client.client_id, initial_balance=Decimal("9000")
        )
        ranking = bank.get_clients_ranking()
        assert ranking[0][0] is rich_client
        assert ranking[0][1] == Decimal("9000")
        assert ranking[1][0] is poor_client
        assert ranking[1][1] == Decimal("100")


class TestPremiumAccountViaBank:
    def test_open_premium_account_with_overdraft(
        self, bank: Bank, client: Client
    ):
        account = bank.open_account(
            client.client_id,
            account_cls=PremiumAccount,
            initial_balance=Decimal("100"),
            overdraft_limit=Decimal("50"),
        )
        bank.withdraw_from_account(account.account_id, Decimal("120"))
        assert account.balance == Decimal("-20")
