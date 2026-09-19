"""
Day 6 - comprehensive demonstration of the whole banking system:
Bank + clients + accounts (Days 1-3), the transaction queue and
processor (Day 4), and risk analysis + audit logging (Day 5), all
working together.
"""

import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from bank.accounts.bank_account import BankAccount
from bank.accounts.investment_account import InvestmentAccount
from bank.accounts.premium_account import PremiumAccount
from bank.accounts.savings_account import SavingsAccount
from bank.audit import AuditLog, RiskAnalyzer
from bank.bank import Bank
from bank.enums import Currency, TransactionType
from bank.exceptions import BankError
from bank.transactions import (
    Transaction,
    TransactionProcessor,
    TransactionQueue,
)

AUDIT_FILE = Path(__file__).parent / "day6_audit_log.jsonl"
DAY_TIME = datetime(2024, 6, 1, 12, 0)
RNG = random.Random(42)


class DemoClock:
    """Mutable callable clock so the demo can move time forward."""

    def __init__(self, now: datetime):
        self._now = now

    def __call__(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def subsection(title: str) -> None:
    print(f"\n--- {title} ---")


def run(processor: TransactionProcessor, transaction: Transaction) -> None:
    """Process one transaction and print its outcome."""
    processor.process(transaction)
    print(transaction)


def create_clients(bank: Bank) -> dict[str, object]:
    roster = [
        ("Anna Volkova", date(1990, 5, 20), "+79990000001", "anna1"),
        ("Oleg Sidorov", date(1985, 3, 12), "+79990000002", "oleg1"),
        ("Maria Popova", date(1992, 7, 15), "+79990000003", "maria1"),
        ("Sergey Titov", date(1988, 11, 2), "+79990000004", "sergey1"),
        ("Pavel Orlov", date(1995, 1, 30), "+79990000005", "pavel1"),
        ("Irina Kuznetsova", date(1991, 9, 9), "+79990000006", "irina1"),
        ("Dmitry Sokolov", date(1983, 4, 18), "+79990000007", "dmitry1"),
        ("Elena Frolova", date(1997, 12, 25), "+79990000008", "elena1"),
    ]
    clients = {}
    for full_name, birth_date, phone, password in roster:
        client = bank.add_client(
            full_name=full_name,
            birth_date=birth_date,
            phone=phone,
            email=f"{password}@example.com",
            password=password,
        )
        clients[full_name] = client
        print(client)
    return clients


def open_accounts(bank: Bank, clients: dict) -> dict[str, BankAccount]:
    a = {}
    a["anna"] = bank.open_account(
        clients["Anna Volkova"].client_id, initial_balance=Decimal("5000000")
    )
    a["anna_savings"] = bank.open_account(
        clients["Anna Volkova"].client_id,
        account_cls=SavingsAccount,
        initial_balance=Decimal("2000000"),
        min_balance=Decimal("100000"),
        monthly_interest_rate=Decimal("0.02"),
    )
    a["oleg"] = bank.open_account(
        clients["Oleg Sidorov"].client_id, initial_balance=Decimal("3000000")
    )
    a["oleg_premium"] = bank.open_account(
        clients["Oleg Sidorov"].client_id,
        account_cls=PremiumAccount,
        initial_balance=Decimal("1000000"),
        withdrawal_limit=Decimal("5000000"),
        overdraft_limit=Decimal("200000"),
        transaction_fee=Decimal("50"),
    )
    a["maria"] = bank.open_account(
        clients["Maria Popova"].client_id, initial_balance=Decimal("200000")
    )
    a["sergey"] = bank.open_account(
        clients["Sergey Titov"].client_id, initial_balance=Decimal("4000000")
    )
    a["sergey_invest"] = bank.open_account(
        clients["Sergey Titov"].client_id,
        account_cls=InvestmentAccount,
        initial_balance=Decimal("1000000"),
    )
    a["pavel"] = bank.open_account(
        clients["Pavel Orlov"].client_id, initial_balance=Decimal("2000000")
    )
    a["irina_usd"] = bank.open_account(
        clients["Irina Kuznetsova"].client_id,
        currency=Currency.USD,
        initial_balance=Decimal("10000"),
    )
    a["irina_savings"] = bank.open_account(
        clients["Irina Kuznetsova"].client_id,
        account_cls=SavingsAccount,
        initial_balance=Decimal("1500000"),
        min_balance=Decimal("50000"),
        monthly_interest_rate=Decimal("0.015"),
    )
    a["dmitry_premium"] = bank.open_account(
        clients["Dmitry Sokolov"].client_id,
        account_cls=PremiumAccount,
        initial_balance=Decimal("500000"),
        withdrawal_limit=Decimal("2000000"),
        overdraft_limit=Decimal("300000"),
        transaction_fee=Decimal("100"),
    )
    a["elena"] = bank.open_account(
        clients["Elena Frolova"].client_id, initial_balance=Decimal("2500000")
    )
    for account in a.values():
        print(account)
    return a


def transfer(
    sender, receiver, amount, external=False, **kwargs
) -> Transaction:
    return Transaction(
        type=(
            TransactionType.EXTERNAL_TRANSFER
            if external
            else TransactionType.TRANSFER
        ),
        amount=Decimal(amount),
        currency=sender.currency,
        sender=sender,
        receiver=receiver,
        **kwargs,
    )


def deposit(receiver, amount, currency=None, **kwargs) -> Transaction:
    return Transaction(
        type=TransactionType.DEPOSIT,
        amount=Decimal(amount),
        currency=currency or receiver.currency,
        receiver=receiver,
        **kwargs,
    )


def withdrawal(sender, amount, **kwargs) -> Transaction:
    return Transaction(
        type=TransactionType.WITHDRAWAL,
        amount=Decimal(amount),
        currency=sender.currency,
        sender=sender,
        **kwargs,
    )


def run_named_scenarios(
    bank: Bank,
    queue: TransactionQueue,
    processor: TransactionProcessor,
    clock: DemoClock,
    acc: dict,
) -> list[Transaction]:
    made: list[Transaction] = []

    subsection("1-3. Обычные операции")
    for tx in (
        deposit(acc["anna"], "10000"),
        deposit(acc["maria"], "200000"),
        withdrawal(acc["pavel"], "50000"),
    ):
        made.append(tx)
        run(processor, tx)

    subsection("4-5. Перевод новому, затем знакомому получателю")
    t4 = transfer(acc["anna"], acc["oleg"], "20000")
    t5 = transfer(acc["anna"], acc["oleg"], "15000")
    made += [t4, t5]
    run(processor, t4)
    run(processor, t5)

    subsection("6. Внешний перевод с комиссией")
    t6 = transfer(acc["oleg"], acc["sergey"], "30000", external=True)
    made.append(t6)
    run(processor, t6)

    subsection("7. Перевод с конвертацией валюты (RUB -> USD)")
    t7 = transfer(acc["sergey"], acc["irina_usd"], "50000")
    made.append(t7)
    run(processor, t7)
    print(f"Баланс USD-счёта: {acc['irina_usd'].balance}")

    subsection("8. Овердрафт премиального счёта")
    t8 = withdrawal(acc["dmitry_premium"], "600000")
    made.append(t8)
    run(processor, t8)
    print(f"Баланс после овердрафта: {acc['dmitry_premium'].balance}")

    subsection("9. Отложенная операция")
    t9 = transfer(
        acc["elena"],
        acc["anna"],
        "10000",
        scheduled_at=clock() + timedelta(hours=1),
    )
    made.append(t9)
    queue.enqueue(t9)
    print(f"Обработано сразу: {len(processor.process_queue(queue))}")
    clock.set(clock() + timedelta(hours=1))
    show_result(processor, queue)

    subsection("10. Отмена транзакции")
    t10 = transfer(acc["pavel"], acc["maria"], "5000")
    made.append(t10)
    queue.enqueue(t10)
    queue.cancel(t10.transaction_id)
    print(f"Обработано после отмены: {len(processor.process_queue(queue))}")
    print(t10)

    subsection("11. ОШИБКА: недостаточно средств")
    t11 = withdrawal(acc["maria"], "999999999")
    made.append(t11)
    run(processor, t11)

    subsection("12. ОШИБКА: операция с замороженным счётом")
    bank.freeze_account(acc["irina_savings"].account_id)
    t12 = deposit(acc["irina_savings"], "1000")
    made.append(t12)
    run(processor, t12)
    bank.unfreeze_account(acc["irina_savings"].account_id)

    subsection("13. ПОДОЗРИТЕЛЬНО: крупная сумма новому получателю -> HIGH")
    t13 = transfer(acc["sergey"], acc["dmitry_premium"], "1000000")
    made.append(t13)
    run(processor, t13)

    subsection("14. ПОДОЗРИТЕЛЬНО: частые операции подряд")
    for _ in range(3):
        tx = withdrawal(acc["pavel"], "1000")
        made.append(tx)
        run(processor, tx)

    return made


def run_night_scenario(risk_analyzer: RiskAnalyzer, clock: DemoClock) -> list:
    """
    Uses two throwaway accounts that were never opened through Bank,
    so this can demonstrate RiskAnalyzer's soft night-time risk flag
    in isolation, without colliding with Bank's separate, stricter
    00:00-05:00 operating-hours restriction (which would otherwise
    hard-block the withdraw()/deposit() call entirely - see day4_demo
    section 10 for that mechanism on its own).
    """
    subsection("15. ПОДОЗРИТЕЛЬНО: ночная операция (не блокируется)")
    night_sender = BankAccount(
        owner="Night Test", initial_balance=Decimal("1000000")
    )
    night_receiver = BankAccount(
        owner="Night Test 2", initial_balance=Decimal("500000")
    )
    processor = TransactionProcessor(risk_analyzer=risk_analyzer, clock=clock)
    priming = transfer(night_sender, night_receiver, "1000")
    processor.process(priming)
    clock.set(datetime(2024, 6, 1, 2, 0))
    night_tx = transfer(night_sender, night_receiver, "1000")
    processor.process(night_tx)
    print(night_tx)
    clock.set(DAY_TIME + timedelta(minutes=10))
    return [priming, night_tx]


def show_result(
    processor: TransactionProcessor, queue: TransactionQueue
) -> None:
    for tx in processor.process_queue(queue):
        print(tx)


def run_bulk_transactions(
    queue: TransactionQueue,
    processor: TransactionProcessor,
    acc: dict,
    count: int,
) -> list[Transaction]:
    pool = [
        acc["anna"],
        acc["anna_savings"],
        acc["oleg"],
        acc["oleg_premium"],
        acc["maria"],
        acc["sergey"],
        acc["sergey_invest"],
        acc["pavel"],
        acc["irina_savings"],
        acc["dmitry_premium"],
        acc["elena"],
    ]
    made: list[Transaction] = []
    for _ in range(count):
        kind = RNG.choices(
            ["deposit", "withdrawal", "transfer"], weights=[3, 3, 4]
        )[0]
        amount = RNG.randint(100, 8000)
        priority = RNG.randint(0, 3)
        if kind == "deposit":
            tx = deposit(RNG.choice(pool), amount, priority=priority)
        elif kind == "withdrawal":
            tx = withdrawal(RNG.choice(pool), amount, priority=priority)
        else:
            sender, receiver = RNG.sample(pool, 2)
            tx = transfer(sender, receiver, amount, priority=priority)
        made.append(tx)
        queue.enqueue(tx)

    print(f"В очереди перед обработкой: {len(queue)}")
    processed = processor.process_queue(queue)
    outcomes: dict[str, int] = {}
    for tx in processed:
        outcomes[tx.status.value] = outcomes.get(tx.status.value, 0) + 1
    print(f"Обработано: {len(processed)} | по статусам: {outcomes}")
    return made


def show_client_scenario(
    bank: Bank, audit_log: AuditLog, full_name: str
) -> None:
    subsection(f"Клиент: {full_name}")
    client = next(c for c in bank.clients.values() if c.full_name == full_name)
    print("Счета:")
    for account_id in client.account_ids:
        print(f"  {bank.accounts[account_id]}")

    history = audit_log.filter(client=full_name)
    print(f"История операций ({len(history)}):")
    for entry in history[-5:]:
        print(f"  {entry}")

    suspicious = [
        e
        for e in audit_log.suspicious_operations_report()
        if e.client == full_name
    ]
    print(f"Подозрительные операции ({len(suspicious)}):")
    for entry in suspicious:
        print(f"  {entry}")


def show_reports(
    bank: Bank, audit_log: AuditLog, all_transactions: list[Transaction]
) -> None:
    section("Отчёты")

    subsection("Топ-3 клиентов по балансу")
    for client, total in bank.get_clients_ranking()[:3]:
        print(f"{client.full_name}: {total}")

    subsection("Статистика транзакций")
    by_status: dict[str, int] = {}
    for tx in all_transactions:
        by_status[tx.status.value] = by_status.get(tx.status.value, 0) + 1
    print(f"Всего транзакций: {len(all_transactions)}")
    print(f"По статусам: {by_status}")
    print(f"Статистика ошибок аудита: {audit_log.error_statistics()}")

    subsection("Общий баланс банка")
    for currency, total in bank.get_total_balance().items():
        print(f"{currency.value}: {total}")


def show_direct_bank_withdrawal(bank: Bank, acc: dict) -> None:
    section("Дополнительно: прямая операция через Bank.withdraw_from_account")
    bank.withdraw_from_account(acc["elena"].account_id, Decimal("1000"))
    print(f"Обычное снятие прошло: баланс {acc['elena'].balance}")
    try:
        bank.withdraw_from_account(acc["elena"].account_id, Decimal("2000000"))
    except BankError as exc:
        print(f"Крупное снятие заблокировано: {exc}")


def main() -> None:
    AUDIT_FILE.unlink(missing_ok=True)

    clock = DemoClock(DAY_TIME)
    audit_log = AuditLog(file_path=AUDIT_FILE, clock=clock)
    risk_analyzer = RiskAnalyzer(
        large_amount_threshold=Decimal("300000"),
        frequent_operations_threshold=3,
        frequent_operations_window=timedelta(minutes=5),
        night_start=time(0, 0),
        night_end=time(5, 0),
        clock=clock,
    )
    bank = Bank(
        name="Day6 Demo Bank",
        clock=clock,
        risk_analyzer=risk_analyzer,
        audit_log=audit_log,
    )
    queue = TransactionQueue(clock=clock)
    processor = TransactionProcessor(
        exchange_rates={(Currency.RUB, Currency.USD): Decimal("0.011")},
        external_transfer_fee_rate=Decimal("0.02"),
        risk_analyzer=risk_analyzer,
        audit_log=audit_log,
        clock=clock,
    )

    section("Инициализация: клиенты")
    clients = create_clients(bank)

    section("Инициализация: счета")
    acc = open_accounts(bank, clients)

    section("Именованные сценарии транзакций")
    all_transactions = run_named_scenarios(bank, queue, processor, clock, acc)
    all_transactions += run_night_scenario(risk_analyzer, clock)

    subsection("16. ПОДОЗРИТЕЛЬНО: комбинация факторов ночью -> HIGH")
    clock.set(datetime(2024, 6, 1, 2, 0))
    t16 = transfer(acc["sergey"], acc["dmitry_premium"], "500000")
    all_transactions.append(t16)
    run(processor, t16)
    clock.set(DAY_TIME + timedelta(minutes=10))

    section("Массовая симуляция (случайные транзакции)")
    all_transactions += run_bulk_transactions(queue, processor, acc, count=24)

    section("Пользовательские сценарии")
    for name in ("Anna Volkova", "Sergey Titov", "Dmitry Sokolov"):
        show_client_scenario(bank, audit_log, name)

    show_reports(bank, audit_log, all_transactions)
    show_direct_bank_withdrawal(bank, acc)

    section("Журнал аудита")
    lines = AUDIT_FILE.read_text(encoding="utf-8").splitlines()
    print(f"{AUDIT_FILE.name}: {len(lines)} записей сохранено на диск")
    print(f"Всего смоделировано транзакций: {len(all_transactions)}")


if __name__ == "__main__":
    main()
