"""
Day 7 - report generation and visualization: text/JSON/CSV reports
plus pie/bar/balance-history charts, built on top of a small but
varied bank simulation (multiple currencies, account types and risk
factors) so the reports exercise as much of the system as possible.
"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from bank.accounts.investment_account import InvestmentAccount
from bank.accounts.premium_account import PremiumAccount
from bank.accounts.savings_account import SavingsAccount
from bank.audit import AuditLog, RiskAnalyzer
from bank.bank import Bank
from bank.enums import Currency, TransactionType
from bank.reports import ReportBuilder
from bank.transactions import Transaction, TransactionProcessor

OUTPUT_DIR = Path(__file__).parent / "day7_reports"
DAY_TIME = datetime(2024, 6, 1, 12, 0)


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def build_bank() -> tuple[Bank, AuditLog, TransactionProcessor, dict, list]:
    audit_log = AuditLog(clock=lambda: DAY_TIME)
    # threshold=4 so the 2-3 incidental operations each account picks
    # up while playing its part in an earlier scenario never trigger
    # this by accident - only the dedicated frequent-operations demo
    # (4 rapid withdrawals from the same account) should trigger it.
    risk_analyzer = RiskAnalyzer(
        large_amount_threshold=Decimal("300000"),
        frequent_operations_threshold=4,
        clock=lambda: DAY_TIME,
    )
    # Bank is NOT given risk_analyzer here: every transaction in this
    # demo flows through TransactionProcessor, which already assesses
    # risk once per transaction. Bank-opened accounts also carry a
    # before_withdraw hook (see Bank.open_account) that would assess
    # risk again on every sender-side operation if Bank had its own
    # risk_analyzer - correct when transactions go through
    # Bank.withdraw_from_account() directly (never used here), but a
    # redundant second assessment (and a second frequency-tracking
    # hit) for transactions already assessed by the processor.
    bank = Bank(
        name="Day7 Demo Bank",
        clock=lambda: DAY_TIME,
        audit_log=audit_log,
    )
    processor = TransactionProcessor(
        exchange_rates={(Currency.RUB, Currency.USD): Decimal("0.011")},
        risk_analyzer=risk_analyzer,
        audit_log=audit_log,
        clock=lambda: DAY_TIME,
    )

    anna = bank.add_client(
        full_name="Anna Volkova",
        birth_date=date(1990, 5, 20),
        phone="+79990000001",
        password="secret0",
    )
    oleg = bank.add_client(
        full_name="Oleg Sidorov",
        birth_date=date(1985, 3, 12),
        phone="+79990000002",
        password="secret1",
    )
    maria = bank.add_client(
        full_name="Maria Popova",
        birth_date=date(1992, 7, 15),
        phone="+79990000003",
        password="secret2",
    )
    sergey = bank.add_client(
        full_name="Sergey Titov",
        birth_date=date(1988, 11, 2),
        phone="+79990000004",
        password="secret3",
    )
    pavel = bank.add_client(
        full_name="Pavel Orlov",
        birth_date=date(1995, 1, 30),
        phone="+79990000005",
        password="secret4",
    )

    accounts = {
        # Anna holds two accounts in two different currencies, so her
        # client report exercises multi-currency balance aggregation.
        "anna_rub": bank.open_account(
            anna.client_id, initial_balance=Decimal("500000")
        ),
        "anna_usd": bank.open_account(
            anna.client_id,
            currency=Currency.USD,
            initial_balance=Decimal("0"),
        ),
        "oleg": bank.open_account(
            oleg.client_id,
            account_cls=PremiumAccount,
            initial_balance=Decimal("100000"),
            withdrawal_limit=Decimal("2000000"),
            overdraft_limit=Decimal("150000"),
            transaction_fee=Decimal("50"),
        ),
        "maria": bank.open_account(
            maria.client_id, initial_balance=Decimal("200000")
        ),
        "sergey": bank.open_account(
            sergey.client_id,
            account_cls=SavingsAccount,
            initial_balance=Decimal("400000"),
            min_balance=Decimal("50000"),
            monthly_interest_rate=Decimal("0.02"),
        ),
        "pavel": bank.open_account(
            pavel.client_id,
            account_cls=InvestmentAccount,
            initial_balance=Decimal("350000"),
        ),
    }

    transactions: list[Transaction] = []

    def run(tx: Transaction) -> Transaction:
        processor.process(tx)
        transactions.append(tx)
        return tx

    # normal transfers, building up account history
    run(
        Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("20000"),
            currency=Currency.RUB,
            sender=accounts["anna_rub"],
            receiver=accounts["oleg"],
        )
    )
    run(
        Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("15000"),
            currency=Currency.RUB,
            sender=accounts["anna_rub"],
            receiver=accounts["oleg"],
        )
    )
    run(
        Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("50000"),
            currency=Currency.RUB,
            receiver=accounts["maria"],
        )
    )
    run(
        Transaction(
            type=TransactionType.DEPOSIT,
            amount=Decimal("100"),
            currency=Currency.USD,
            receiver=accounts["anna_usd"],
        )
    )
    run(
        Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("10000"),
            currency=Currency.RUB,
            sender=accounts["sergey"],
        )
    )
    run(
        Transaction(
            type=TransactionType.EXTERNAL_TRANSFER,
            amount=Decimal("25000"),
            currency=Currency.RUB,
            sender=accounts["pavel"],
            receiver=accounts["maria"],
        )
    )
    # currency conversion: sergey (RUB) -> anna's USD account
    run(
        Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("30000"),
            currency=Currency.RUB,
            sender=accounts["sergey"],
            receiver=accounts["anna_usd"],
        )
    )
    # premium overdraft: goes negative, within the account's own limit
    run(
        Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("250000"),
            currency=Currency.RUB,
            sender=accounts["oleg"],
        )
    )
    # an ordinary failure: no risk factors block it, it just fails
    run(
        Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("999999999"),
            currency=Currency.RUB,
            sender=accounts["maria"],
        )
    )
    # suspicious, blocked: large amount to a new recipient
    run(
        Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("600000"),
            currency=Currency.RUB,
            sender=accounts["sergey"],
            receiver=accounts["pavel"],
        )
    )
    # suspicious, allowed: frequent operations from the same account
    for _ in range(4):
        run(
            Transaction(
                type=TransactionType.WITHDRAWAL,
                amount=Decimal("5000"),
                currency=Currency.RUB,
                sender=accounts["pavel"],
            )
        )

    return bank, audit_log, processor, accounts, transactions


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    section("Симуляция")
    bank, audit_log, processor, accounts, transactions = build_bank()
    for tx in transactions:
        print(tx)

    builder = ReportBuilder(bank, audit_log, clock=lambda: DAY_TIME)

    section("Отчёты по клиентам")
    for client in bank.clients.values():
        client_report = builder.client_report(client)
        print(client_report.to_text())
        print()
        slug = client.full_name.lower().replace(" ", "_")
        ReportBuilder.export_to_json(
            client_report, OUTPUT_DIR / f"client_{slug}.json"
        )
        ReportBuilder.export_to_csv(
            client_report, OUTPUT_DIR / f"client_{slug}.csv"
        )

    section("Отчёт по банку")
    bank_report = builder.bank_report()
    print(bank_report.to_text())
    ReportBuilder.export_to_json(bank_report, OUTPUT_DIR / "bank.json")
    ReportBuilder.export_to_csv(bank_report, OUTPUT_DIR / "bank.csv")

    section("Отчёт по рискам")
    risk_report = builder.risk_report()
    print(risk_report.to_text())
    ReportBuilder.export_to_json(risk_report, OUTPUT_DIR / "risk.json")
    ReportBuilder.export_to_csv(risk_report, OUTPUT_DIR / "risk.csv")

    section("Диаграммы")
    total_balance = bank.get_total_balance()
    pie = ReportBuilder.pie_chart(
        {currency.value: amount for currency, amount in total_balance.items()},
        "Баланс банка по валютам",
    )
    ranking = bank.get_clients_ranking()
    bar = ReportBuilder.bar_chart(
        {client.full_name: total for client, total in ranking},
        "Баланс по клиентам",
        xlabel="Клиент",
        ylabel="Баланс (RUB)",
    )
    anna_rub_line = builder.balance_history_chart(
        accounts["anna_rub"],
        transactions,
        title="Движение баланса: Anna Volkova (RUB)",
    )
    anna_usd_line = builder.balance_history_chart(
        accounts["anna_usd"],
        transactions,
        title="Движение баланса: Anna Volkova (USD)",
    )
    saved = ReportBuilder.save_charts(
        {
            "balances_pie": pie,
            "clients_bar": bar,
            "anna_rub_balance_line": anna_rub_line,
            "anna_usd_balance_line": anna_usd_line,
        },
        OUTPUT_DIR / "charts",
    )
    for path in saved:
        print(f"Сохранено: {path}")

    section("Итог")
    file_count = sum(1 for path in OUTPUT_DIR.rglob("*") if path.is_file())
    print(f"Отчёты и графики сохранены в: {OUTPUT_DIR}")
    print(f"Файлов в каталоге: {file_count}")


if __name__ == "__main__":
    main()
