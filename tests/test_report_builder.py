from datetime import date, datetime
from decimal import Decimal

import pytest
from matplotlib.figure import Figure

from bank.audit import AuditLog
from bank.bank import Bank
from bank.enums import Currency, ReportType, TransactionType
from bank.exceptions import InvalidOperationError
from bank.reports import ReportBuilder
from bank.transactions import Transaction, TransactionProcessor

DAY_TIME = datetime(2024, 1, 1, 12, 0, 0)


def make_bank_with_clients():
    audit_log = AuditLog(clock=lambda: DAY_TIME)
    bank = Bank(name="Test Bank", clock=lambda: DAY_TIME, audit_log=audit_log)
    anna = bank.add_client(
        full_name="Anna Volkova",
        birth_date=date(1990, 1, 1),
        phone="+79990000001",
        password="secret123",
    )
    oleg = bank.add_client(
        full_name="Oleg Sidorov",
        birth_date=date(1985, 1, 1),
        phone="+79990000002",
        password="secret123",
    )
    anna_account = bank.open_account(
        anna.client_id, initial_balance=Decimal("100000")
    )
    oleg_account = bank.open_account(
        oleg.client_id, initial_balance=Decimal("50000")
    )
    return bank, audit_log, anna, oleg, anna_account, oleg_account


@pytest.fixture
def report_setup():
    bank, audit_log, anna, oleg, anna_account, oleg_account = (
        make_bank_with_clients()
    )
    processor = TransactionProcessor(
        audit_log=audit_log, clock=lambda: DAY_TIME
    )
    tx = Transaction(
        type=TransactionType.TRANSFER,
        amount=Decimal("5000"),
        currency=Currency.RUB,
        sender=anna_account,
        receiver=oleg_account,
    )
    processor.process(tx)
    builder = ReportBuilder(bank, audit_log, clock=lambda: DAY_TIME)
    return {
        "bank": bank,
        "audit_log": audit_log,
        "anna": anna,
        "oleg": oleg,
        "anna_account": anna_account,
        "oleg_account": oleg_account,
        "tx": tx,
        "builder": builder,
    }


class TestConstruction:
    def test_rejects_non_bank(self):
        with pytest.raises(InvalidOperationError):
            ReportBuilder(object(), AuditLog())

    def test_rejects_non_audit_log(self, bank: Bank):
        with pytest.raises(InvalidOperationError):
            ReportBuilder(bank, object())


class TestClientReport:
    def test_rejects_non_client(self, report_setup):
        with pytest.raises(InvalidOperationError):
            report_setup["builder"].client_report(object())

    def test_summary_reflects_accounts_and_balance(self, report_setup):
        report = report_setup["builder"].client_report(report_setup["anna"])
        assert report.report_type == ReportType.CLIENT
        assert report.summary["full_name"] == "Anna Volkova"
        assert report.summary["account_count"] == 1
        assert report.summary["balances_by_currency"] == {"RUB": "95000"}

    def test_rows_list_the_accounts(self, report_setup):
        report = report_setup["builder"].client_report(report_setup["anna"])
        assert len(report.rows) == 1
        assert report.rows[0]["account_id"] == (
            report_setup["anna_account"].account_id
        )
        assert report.rows[0]["balance"] == "95000"

    def test_client_with_no_accounts_has_empty_rows(self):
        bank, audit_log, *_ = make_bank_with_clients()
        empty_client = bank.add_client(
            full_name="Empty Client",
            birth_date=date(1990, 1, 1),
            phone="+79990000009",
            password="secret123",
        )
        builder = ReportBuilder(bank, audit_log, clock=lambda: DAY_TIME)
        report = builder.client_report(empty_client)
        assert report.rows == []
        assert report.summary["account_count"] == 0


class TestBankReport:
    def test_summary_reflects_bank_state(self, report_setup):
        report = report_setup["builder"].bank_report()
        assert report.report_type == ReportType.BANK
        assert report.summary["bank_name"] == "Test Bank"
        assert report.summary["client_count"] == 2
        assert report.summary["account_count"] == 2
        assert report.summary["total_balance"] == {"RUB": "150000"}

    def test_rows_rank_clients_by_balance(self, report_setup):
        report = report_setup["builder"].bank_report()
        assert report.rows[0]["client"] == "Anna Volkova"
        assert report.rows[0]["rank"] == 1
        assert report.rows[1]["client"] == "Oleg Sidorov"
        assert report.rows[1]["rank"] == 2


class TestRiskReport:
    def test_summary_reflects_audit_log(self, report_setup):
        report = report_setup["builder"].risk_report()
        assert report.report_type == ReportType.RISK
        # one transaction -> one audit entry, attributed to the
        # sender (see TransactionProcessor._log_outcome)
        assert report.summary["total_audit_entries"] == 1
        assert "error_statistics" in report.summary

    def test_empty_when_nothing_suspicious(self, report_setup):
        report = report_setup["builder"].risk_report()
        assert report.rows == []


class TestExport:
    def test_export_to_json_writes_valid_json(self, report_setup, tmp_path):
        import json

        report = report_setup["builder"].bank_report()
        path = ReportBuilder.export_to_json(report, tmp_path / "bank.json")
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["title"] == report.title

    def test_export_to_csv_writes_header_and_rows(
        self, report_setup, tmp_path
    ):
        report = report_setup["builder"].bank_report()
        path = ReportBuilder.export_to_csv(report, tmp_path / "bank.csv")
        assert path.exists()
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "rank,client,total_balance"
        assert len(lines) == 1 + len(report.rows)

    def test_export_to_csv_with_empty_rows_still_writes_header(
        self, report_setup, tmp_path
    ):
        report = report_setup["builder"].risk_report()
        path = ReportBuilder.export_to_csv(report, tmp_path / "risk.csv")
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines == [",".join(report.fieldnames)]


class TestCharts:
    def test_pie_chart_returns_a_figure(self):
        fig = ReportBuilder.pie_chart({"RUB": 100, "USD": 50}, "Balances")
        assert isinstance(fig, Figure)

    def test_pie_chart_rejects_empty_data(self):
        with pytest.raises(InvalidOperationError):
            ReportBuilder.pie_chart({}, "Balances")

    def test_bar_chart_returns_a_figure(self):
        fig = ReportBuilder.bar_chart({"Anna": 100, "Oleg": 50}, "Top clients")
        assert isinstance(fig, Figure)

    def test_bar_chart_rejects_empty_data(self):
        with pytest.raises(InvalidOperationError):
            ReportBuilder.bar_chart({}, "Top clients")

    def test_balance_history_chart_with_transactions(self, report_setup):
        fig = report_setup["builder"].balance_history_chart(
            report_setup["anna_account"], [report_setup["tx"]]
        )
        assert isinstance(fig, Figure)

    def test_balance_history_chart_with_no_transactions(self, report_setup):
        fig = report_setup["builder"].balance_history_chart(
            report_setup["oleg_account"], []
        )
        assert isinstance(fig, Figure)

    def test_balance_history_reconstructs_correct_values(self, report_setup):
        # anna started at 100000, sent 5000 (no fee for TRANSFER) to
        # oleg, ending at 95000 - the reconstruction must produce
        # exactly [100000, 95000], regardless of chart rendering.
        timestamps, balances = report_setup[
            "builder"
        ]._reconstruct_balance_history(
            report_setup["anna_account"], [report_setup["tx"]]
        )
        assert balances == [Decimal("100000"), Decimal("95000")]
        assert len(timestamps) == 2


class TestSaveCharts:
    def test_saves_each_chart_as_png(self, tmp_path):
        charts = {
            "pie": ReportBuilder.pie_chart({"a": 1}, "A"),
            "bar": ReportBuilder.bar_chart({"a": 1}, "A"),
        }
        saved = ReportBuilder.save_charts(charts, tmp_path / "charts")
        assert len(saved) == 2
        for path in saved:
            assert path.exists()
            assert path.stat().st_size > 0
            assert path.suffix == ".png"

    def test_rejects_empty_charts(self, tmp_path):
        with pytest.raises(InvalidOperationError):
            ReportBuilder.save_charts({}, tmp_path / "charts")

    def test_creates_missing_directory(self, tmp_path):
        target = tmp_path / "nested" / "charts"
        ReportBuilder.save_charts(
            {"pie": ReportBuilder.pie_chart({"a": 1}, "A")}, target
        )
        assert target.is_dir()
