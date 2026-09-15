from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal

from bank.accounts.premium_account import PremiumAccount
from bank.bank import Bank
from bank.enums import Currency, TransactionType
from bank.transactions import (
    Transaction,
    TransactionProcessor,
    TransactionQueue,
)


class DemoClock:
    """
    Mutable callable clock so the demo can move time forward to
    exercise deferred transactions and the night restriction.
    """

    def __init__(self, now: datetime):
        self._now = now

    def __call__(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now


def section(title: str) -> None:
    """
    Print a titled section separator to the console.

    :param title: section title to display
    :return: None
    """
    print(f"\n--- {title} ---")


def show(*transactions: Transaction) -> None:
    """
    Print each transaction's string representation.

    :param transactions: transactions to display
    :return: None
    """
    for transaction in transactions:
        print(transaction)


def show_accounts(*accounts) -> None:
    """
    Print each account's string representation.

    :param accounts: accounts to display
    :return: None
    """
    print("Состояние счетов:")
    for account in accounts:
        print(account)


def main() -> None:
    """
    Run the day 4 demo: 10 transactions of different kinds, queued
    with priorities and a deferred schedule, then processed.

    :return: None
    """
    clock: Callable[[], datetime] = DemoClock(datetime(2024, 6, 1, 12, 0))
    bank = Bank(name="Demo Bank", clock=clock)
    queue = TransactionQueue(clock=clock)
    processor = TransactionProcessor(
        exchange_rates={(Currency.RUB, Currency.USD): Decimal("0.011")},
        external_transfer_fee_rate=Decimal("0.02"),
        max_retries=3,
        clock=clock,
    )

    section("Клиенты и счета")
    anna = bank.add_client(
        full_name="Anna Volkova",
        birth_date=date(1990, 5, 20),
        phone="+79990000001",
        email="anna@example.com",
        password="anna-secret",
    )
    oleg = bank.add_client(
        full_name="Oleg Sidorov",
        birth_date=date(1985, 3, 12),
        phone="+79990000002",
        password="oleg-secret",
    )
    maria = bank.add_client(
        full_name="Maria Popova",
        birth_date=date(1992, 7, 15),
        phone="+79990000003",
        password="maria-secret",
    )

    anna_account = bank.open_account(
        anna.client_id, currency=Currency.RUB, initial_balance=Decimal("5000")
    )
    oleg_account = bank.open_account(
        oleg.client_id, currency=Currency.RUB, initial_balance=Decimal("3000")
    )
    oleg_usd_account = bank.open_account(
        oleg.client_id, currency=Currency.USD, initial_balance=Decimal("200")
    )
    maria_premium = bank.open_account(
        maria.client_id,
        account_cls=PremiumAccount,
        currency=Currency.RUB,
        initial_balance=Decimal("100"),
        overdraft_limit=Decimal("500"),
    )
    all_accounts = (
        anna_account,
        oleg_account,
        oleg_usd_account,
        maria_premium,
    )
    show_accounts(*all_accounts)

    section("1-2. Приоритет в очереди")
    t1 = Transaction(
        type=TransactionType.DEPOSIT,
        amount=Decimal("1000"),
        currency=Currency.RUB,
        receiver=anna_account,
        priority=1,
    )
    t2 = Transaction(
        type=TransactionType.WITHDRAWAL,
        amount=Decimal("500"),
        currency=Currency.RUB,
        sender=oleg_account,
        priority=5,
    )
    queue.enqueue(t1)
    queue.enqueue(t2)
    processed = processor.process_queue(queue)
    print("Порядок обработки (по приоритету):")
    show(*processed)
    show_accounts(*all_accounts)

    section("3-4. Внутренний перевод и внешний перевод с комиссией")
    t3 = Transaction(
        type=TransactionType.TRANSFER,
        amount=Decimal("300"),
        currency=Currency.RUB,
        sender=anna_account,
        receiver=oleg_account,
    )
    t4 = Transaction(
        type=TransactionType.EXTERNAL_TRANSFER,
        amount=Decimal("200"),
        currency=Currency.RUB,
        sender=oleg_account,
        receiver=maria_premium,
    )
    queue.enqueue(t3)
    queue.enqueue(t4)
    show(*processor.process_queue(queue))
    show_accounts(*all_accounts)

    section("5. Перевод с конвертацией валюты (RUB -> USD)")
    t5 = Transaction(
        type=TransactionType.TRANSFER,
        amount=Decimal("1000"),
        currency=Currency.RUB,
        sender=anna_account,
        receiver=oleg_usd_account,
    )
    queue.enqueue(t5)
    show(*processor.process_queue(queue))
    print(f"Баланс USD-счёта после конвертации: {oleg_usd_account.balance}")
    show_accounts(*all_accounts)

    section("6. Отложенная операция")
    t6 = Transaction(
        type=TransactionType.TRANSFER,
        amount=Decimal("100"),
        currency=Currency.RUB,
        sender=anna_account,
        receiver=oleg_account,
        scheduled_at=clock() + timedelta(hours=1),
    )
    queue.enqueue(t6)
    print(f"Обработано сразу: {len(processor.process_queue(queue))}")
    print(f"Остаётся в очереди (ещё не наступило время): {len(queue)}")
    clock.set(clock() + timedelta(hours=1))
    show(*processor.process_queue(queue))
    show_accounts(*all_accounts)

    section("7. Отмена транзакции")
    t7 = Transaction(
        type=TransactionType.TRANSFER,
        amount=Decimal("50"),
        currency=Currency.RUB,
        sender=anna_account,
        receiver=oleg_account,
    )
    queue.enqueue(t7)
    queue.cancel(t7.transaction_id)
    print(f"Обработано после отмены: {len(processor.process_queue(queue))}")
    print(t7)
    show_accounts(*all_accounts)

    section("8. Недостаточно средств")
    t8 = Transaction(
        type=TransactionType.WITHDRAWAL,
        amount=Decimal("999999"),
        currency=Currency.RUB,
        sender=oleg_account,
    )
    queue.enqueue(t8)
    show(*processor.process_queue(queue))
    show_accounts(*all_accounts)

    section("9. Операция с замороженным счётом")
    bank.freeze_account(maria_premium.account_id)
    t9 = Transaction(
        type=TransactionType.DEPOSIT,
        amount=Decimal("100"),
        currency=Currency.RUB,
        receiver=maria_premium,
    )
    queue.enqueue(t9)
    show(*processor.process_queue(queue))
    show_accounts(*all_accounts)
    bank.unfreeze_account(maria_premium.account_id)

    section("10. Запрет операций ночью и повторные попытки")
    clock.set(datetime(2024, 6, 1, 2, 0))
    t10 = Transaction(
        type=TransactionType.DEPOSIT,
        amount=Decimal("100"),
        currency=Currency.RUB,
        receiver=anna_account,
    )
    queue.enqueue(t10)
    show(*processor.process_queue(queue))
    print(f"Число попыток: {t10.attempts}")
    show_accounts(*all_accounts)
    clock.set(datetime(2024, 6, 1, 12, 0))

    section("Итог по всем 10 транзакциям")
    show(t1, t2, t3, t4, t5, t6, t7, t8, t9, t10)


if __name__ == "__main__":
    main()
