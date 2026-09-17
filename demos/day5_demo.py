from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from bank.accounts.bank_account import BankAccount
from bank.audit import AuditLog, RiskAnalyzer
from bank.enums import Currency, TransactionType
from bank.transactions import Transaction, TransactionProcessor

AUDIT_FILE = Path(__file__).parent / "day5_audit_log.jsonl"


class DemoClock:
    """
    Mutable callable clock so the demo can move time forward to
    exercise night-hours risk detection.
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


def run(processor: TransactionProcessor, transaction: Transaction) -> None:
    """
    Process a transaction and print its outcome.

    :param processor: processor to run the transaction through
    :param transaction: transaction to process
    :return: None
    """
    processor.process(transaction)
    print(transaction)


def main() -> None:
    """
    Run the day 5 demo: a mix of normal and suspicious transactions
    processed through a risk-aware TransactionProcessor, showing
    audit persistence (memory + file) and the three audit reports.

    :return: None
    """
    AUDIT_FILE.unlink(missing_ok=True)

    clock = DemoClock(datetime(2024, 6, 1, 12, 0))
    audit_log = AuditLog(file_path=AUDIT_FILE, clock=clock)
    risk_analyzer = RiskAnalyzer(
        large_amount_threshold=Decimal("500000"),
        frequent_operations_threshold=3,
        frequent_operations_window=timedelta(minutes=5),
        night_start=time(0, 0),
        night_end=time(5, 0),
        clock=clock,
    )
    processor = TransactionProcessor(
        risk_analyzer=risk_analyzer, audit_log=audit_log, clock=clock
    )

    section("Счета")
    anna = BankAccount(
        owner="Anna Volkova",
        currency=Currency.RUB,
        initial_balance=Decimal("3000000"),
    )
    oleg = BankAccount(
        owner="Oleg Sidorov",
        currency=Currency.RUB,
        initial_balance=Decimal("1000000"),
    )
    maria = BankAccount(
        owner="Maria Popova",
        currency=Currency.RUB,
        initial_balance=Decimal("2000000"),
    )
    sergey = BankAccount(
        owner="Sergey Titov",
        currency=Currency.RUB,
        initial_balance=Decimal("5000000"),
    )
    pavel = BankAccount(
        owner="Pavel Orlov",
        currency=Currency.RUB,
        initial_balance=Decimal("1500000"),
    )
    poor = BankAccount(
        owner="Poor Client",
        currency=Currency.RUB,
        initial_balance=Decimal("500"),
    )
    for acc in (anna, oleg, maria, sergey, pavel, poor):
        print(acc)

    section("1. Первый перевод новому получателю -> MEDIUM (new_recipient)")
    run(
        processor,
        Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("1000"),
            currency=Currency.RUB,
            sender=anna,
            receiver=oleg,
        ),
    )

    section("2. Повторный перевод знакомому получателю -> LOW")
    run(
        processor,
        Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("1500"),
            currency=Currency.RUB,
            sender=anna,
            receiver=oleg,
        ),
    )

    section("3. Третий перевод подряд -> MEDIUM (frequent_operations)")
    run(
        processor,
        Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("2000"),
            currency=Currency.RUB,
            sender=anna,
            receiver=oleg,
        ),
    )

    section(
        "4. Крупная сумма новому получателю -> HIGH, заблокировано "
        "(large_amount + new_recipient)"
    )
    run(
        processor,
        Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("800000"),
            currency=Currency.RUB,
            sender=oleg,
            receiver=maria,
        ),
    )

    section(
        "5. Небольшой перевод той же паре после блокировки -> всё ещё "
        "MEDIUM (new_recipient), т.к. заблокированная попытка не даёт "
        "получателю доверия — иначе блокировку можно было бы обойти "
        "простой повторной отправкой"
    )
    run(
        processor,
        Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("1500"),
            currency=Currency.RUB,
            sender=oleg,
            receiver=maria,
        ),
    )

    section(
        "5b. Тот же перевод ещё раз -> теперь LOW: получатель стал "
        "известен только после того, как перевод #5 реально завершился"
    )
    run(
        processor,
        Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("1500"),
            currency=Currency.RUB,
            sender=oleg,
            receiver=maria,
        ),
    )

    section("6a. Дневной перевод, чтобы получатель стал известен")
    run(
        processor,
        Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("300"),
            currency=Currency.RUB,
            sender=sergey,
            receiver=pavel,
        ),
    )

    section("6b. Ночная операция -> MEDIUM (night_operation)")
    clock.set(datetime(2024, 6, 1, 2, 0))
    run(
        processor,
        Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("300"),
            currency=Currency.RUB,
            sender=sergey,
            receiver=pavel,
        ),
    )

    section(
        "7. Комбинация факторов ночью -> HIGH, заблокировано "
        "(large_amount + new_recipient + night_operation + "
        "frequent_operations)"
    )
    run(
        processor,
        Transaction(
            type=TransactionType.TRANSFER,
            amount=Decimal("600000"),
            currency=Currency.RUB,
            sender=sergey,
            receiver=maria,
        ),
    )
    clock.set(datetime(2024, 6, 1, 12, 0))

    section("8. Недостаточно средств -> обычный отказ, не связанный с риском")
    run(
        processor,
        Transaction(
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("10000"),
            currency=Currency.RUB,
            sender=poor,
        ),
    )

    section("Отчёт: подозрительные операции")
    for entry in audit_log.suspicious_operations_report():
        print(entry)

    section("Отчёт: риск-профиль клиента")
    for client in ("Anna Volkova", "Oleg Sidorov", "Sergey Titov"):
        print(audit_log.client_risk_profile(client))

    section("Отчёт: статистика ошибок")
    print(audit_log.error_statistics())

    section("Файл журнала аудита")
    lines = AUDIT_FILE.read_text(encoding="utf-8").splitlines()
    print(f"{AUDIT_FILE.name}: {len(lines)} записей сохранено на диск")
    print(lines[0])


if __name__ == "__main__":
    main()
