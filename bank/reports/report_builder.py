import csv
import json
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import matplotlib
from matplotlib.figure import Figure

from bank.accounts.bank_account import BankAccount
from bank.audit.audit_log import AuditLog
from bank.bank import Bank
from bank.client import Client
from bank.enums import ReportType, TransactionStatus
from bank.exceptions import InvalidOperationError
from bank.reports.report import Report
from bank.transactions.transaction import Transaction

matplotlib.use("Agg")  # non-interactive backend; must be set before pyplot
# is imported below, so this module never tries to open a GUI window,
# which would fail or hang on a headless machine (CI, servers).
import matplotlib.pyplot as plt  # noqa: E402


class ReportBuilder:
    """
    Builds text/JSON/CSV reports and matplotlib charts from a Bank's
    and AuditLog's current state.
    """

    def __init__(
        self,
        bank: Bank,
        audit_log: AuditLog,
        clock: Callable[[], datetime] = datetime.now,
    ):
        """
        Create a report builder.

        :param bank: bank to read clients/accounts/balances from
        :param audit_log: audit log to read history/risk data from
        :param clock: callable returning the current datetime, used
            to stamp generated reports
        """
        if not isinstance(bank, Bank):
            raise InvalidOperationError(f"Expected a Bank, got {bank!r}")
        if not isinstance(audit_log, AuditLog):
            raise InvalidOperationError(
                f"Expected an AuditLog, got {audit_log!r}"
            )
        self._bank = bank
        self._audit_log = audit_log
        self._clock = clock

    def client_report(self, client: Client) -> Report:
        """
        Build a report summarizing one client: their accounts,
        combined balances and risk history.

        :param client: client to report on
        :return: the built report
        """
        if not isinstance(client, Client):
            raise InvalidOperationError(f"Expected a Client, got {client!r}")
        accounts = [
            self._bank.accounts[account_id]
            for account_id in client.account_ids
            if account_id in self._bank.accounts
        ]
        balances: dict[str, Decimal] = {}
        for account in accounts:
            key = account.currency.value
            balances[key] = balances.get(key, Decimal("0")) + account.balance
        profile = self._audit_log.client_risk_profile(client.full_name)

        summary = {
            "client_id": client.client_id,
            "full_name": client.full_name,
            "status": client.status.value,
            "age": client.age,
            "is_suspicious": client.is_suspicious,
            "suspicious_reasons": client.suspicious_reasons,
            "account_count": len(accounts),
            "balances_by_currency": {
                currency: str(amount) for currency, amount in balances.items()
            },
            "risk_operations": profile["total_operations"],
            "risk_reasons": profile["risk_reasons"],
        }
        fieldnames = ["account_id", "type", "currency", "balance", "status"]
        rows = [
            {
                "account_id": account.account_id,
                "type": type(account).__name__,
                "currency": account.currency.value,
                "balance": str(account.balance),
                "status": account.status.value,
            }
            for account in accounts
        ]
        return Report(
            report_type=ReportType.CLIENT,
            title=f"Отчёт по клиенту: {client.full_name}",
            generated_at=self._clock(),
            summary=summary,
            fieldnames=fieldnames,
            rows=rows,
        )

    def bank_report(self) -> Report:
        """
        Build a report summarizing the whole bank: totals and the
        full client ranking.

        :return: the built report
        """
        total_balance = self._bank.get_total_balance()
        ranking = self._bank.get_clients_ranking()
        summary = {
            "bank_name": self._bank.name,
            "client_count": len(self._bank.clients),
            "account_count": len(self._bank.accounts),
            "total_balance": {
                currency.value: str(amount)
                for currency, amount in total_balance.items()
            },
        }
        fieldnames = ["rank", "client", "total_balance"]
        rows = [
            {
                "rank": rank,
                "client": client.full_name,
                "total_balance": str(total),
            }
            for rank, (client, total) in enumerate(ranking, start=1)
        ]
        return Report(
            report_type=ReportType.BANK,
            title=f"Отчёт по банку: {self._bank.name}",
            generated_at=self._clock(),
            summary=summary,
            fieldnames=fieldnames,
            rows=rows,
        )

    def risk_report(self) -> Report:
        """
        Build a report summarizing risk activity: every entry the
        audit log flagged as suspicious, plus error statistics.

        :return: the built report
        """
        suspicious = self._audit_log.suspicious_operations_report()
        summary = {
            "total_audit_entries": len(self._audit_log.entries),
            "suspicious_count": len(suspicious),
            "error_statistics": self._audit_log.error_statistics(),
        }
        fieldnames = [
            "timestamp",
            "client",
            "account_id",
            "event",
            "severity",
            "risk_level",
            "risk_reasons",
        ]
        rows = [
            {
                "timestamp": entry.timestamp.isoformat(),
                "client": entry.client,
                "account_id": entry.account_id,
                "event": entry.event,
                "severity": entry.severity.value,
                "risk_level": entry.metadata.get("risk_level"),
                "risk_reasons": ", ".join(
                    entry.metadata.get("risk_reasons") or []
                ),
            }
            for entry in suspicious
        ]
        return Report(
            report_type=ReportType.RISK,
            title="Отчёт по рискам",
            generated_at=self._clock(),
            summary=summary,
            fieldnames=fieldnames,
            rows=rows,
        )

    @staticmethod
    def export_to_json(report: Report, path: str | Path) -> Path:
        """
        Write a report to disk as JSON.

        :param report: report to export
        :param path: file path to write to
        :return: the path written to
        """
        path = Path(path)
        path.write_text(
            json.dumps(
                report.to_dict(), ensure_ascii=False, indent=2, default=str
            ),
            encoding="utf-8",
        )
        return path

    @staticmethod
    def export_to_csv(report: Report, path: str | Path) -> Path:
        """
        Write a report's rows to disk as CSV, using its fieldnames
        as the header row.

        :param report: report to export
        :param path: file path to write to
        :return: the path written to
        """
        path = Path(path)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=report.fieldnames)
            writer.writeheader()
            writer.writerows(report.rows)
        return path

    @staticmethod
    def pie_chart(
        data: dict[str, Decimal | float | int], title: str
    ) -> Figure:
        """
        Build a pie chart from a label -> value mapping.

        :param data: values to chart, keyed by label
        :param title: chart title
        :return: the built figure
        """
        if not data:
            raise InvalidOperationError("Chart data must not be empty")
        fig, ax = plt.subplots()
        ax.pie(
            [float(value) for value in data.values()],
            labels=list(data.keys()),
            autopct="%1.1f%%",
        )
        ax.set_title(title)
        return fig

    @staticmethod
    def bar_chart(
        data: dict[str, Decimal | float | int],
        title: str,
        xlabel: str = "",
        ylabel: str = "",
    ) -> Figure:
        """
        Build a bar chart from a label -> value mapping.

        :param data: values to chart, keyed by label
        :param title: chart title
        :param xlabel: x-axis label
        :param ylabel: y-axis label
        :return: the built figure
        """
        if not data:
            raise InvalidOperationError("Chart data must not be empty")
        fig, ax = plt.subplots()
        ax.bar(list(data.keys()), [float(value) for value in data.values()])
        ax.set_title(title)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        fig.autofmt_xdate(rotation=30)
        return fig

    def balance_history_chart(
        self,
        account: BankAccount,
        transactions: list[Transaction],
        title: str | None = None,
    ) -> Figure:
        """
        Build a line chart of an account's balance over time,
        reconstructed from its completed transactions.

        :param account: account to chart
        :param transactions: transactions to search for ones
            involving this account (as sender or receiver);
            transactions in any other status are ignored
        :param title: chart title, defaults to a generated one
        :return: the built figure
        """
        timestamps, balances = self._reconstruct_balance_history(
            account, transactions
        )
        fig, ax = plt.subplots()
        ax.plot(timestamps, [float(b) for b in balances], marker="o")
        ax.set_title(title or f"Движение баланса: {account.account_id}")
        ax.set_xlabel("Время")
        ax.set_ylabel(f"Баланс ({account.currency.value})")
        fig.autofmt_xdate(rotation=30)
        return fig

    def _reconstruct_balance_history(
        self, account: BankAccount, transactions: list[Transaction]
    ) -> tuple[list[datetime], list[Decimal]]:
        """
        Reconstruct an account's balance at each of its completed
        transactions, working backward from its current (always
        authoritative) balance. Cross-currency credits are treated
        as if no conversion happened (the transaction's raw amount
        is used), since the exact converted amount is not retained
        on the Transaction - this is a simplification, consistent
        with similar ones already made elsewhere in this project
        (e.g. Bank.get_clients_ranking() also sums currencies
        without converting them).

        :param account: account to reconstruct history for
        :param transactions: transactions to search for ones
            involving this account
        :return: (timestamps, balances), one more timestamp than
            transaction if any are found (an implied starting
            point), otherwise a single point at the current balance
        """
        relevant = sorted(
            (
                tx
                for tx in transactions
                if tx.status == TransactionStatus.COMPLETED
                and (tx.sender is account or tx.receiver is account)
            ),
            key=lambda tx: tx.processed_at or tx.created_at,
        )
        if not relevant:
            return [self._clock()], [account.balance]

        deltas = []
        for tx in relevant:
            if tx.sender is account:
                deltas.append(-(tx.amount + tx.fee))
            else:
                deltas.append(tx.amount)
        starting_balance = account.balance - sum(deltas, Decimal("0"))

        timestamps = [relevant[0].created_at]
        balances = [starting_balance]
        running = starting_balance
        for tx, delta in zip(relevant, deltas, strict=True):
            running += delta
            timestamps.append(tx.processed_at or tx.created_at)
            balances.append(running)
        return timestamps, balances

    @staticmethod
    def save_charts(
        charts: dict[str, Figure], directory: str | Path
    ) -> list[Path]:
        """
        Save each chart as a PNG file named after its key.

        :param charts: figures to save, keyed by file name (without
            extension)
        :param directory: directory to save into; created if needed
        :return: list of paths written to, in the same order as
            `charts`
        """
        if not charts:
            raise InvalidOperationError("Charts must not be empty")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        saved = []
        for name, figure in charts.items():
            path = directory / f"{name}.png"
            figure.savefig(path)
            plt.close(figure)
            saved.append(path)
        return saved
