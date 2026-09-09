from decimal import Decimal

from bank.accounts import BankAccount
from bank.enums import Currency
from bank.exceptions import (
    AccountFrozenError,
    InsufficientFundsError,
    InvalidOperationError,
)


def section(title: str) -> None:
    print(f"\n--- {title} ---")


def main() -> None:
    section("Создание счетов")
    active_account = BankAccount(
        owner="Иван Петров", currency=Currency.RUB, initial_balance=Decimal("1000")
    )
    frozen_account = BankAccount(
        owner="Мария Смирнова",
        currency=Currency.USD,
        initial_balance=Decimal("500"),
    )
    frozen_account.freeze()
    print(active_account)
    print(frozen_account)

    section("Операции над замороженным счётом")
    try:
        frozen_account.deposit(Decimal("100"))
    except AccountFrozenError as exc:
        print(f"Ожидаемая ошибка: {exc}")

    try:
        frozen_account.withdraw(Decimal("50"))
    except AccountFrozenError as exc:
        print(f"Ожидаемая ошибка: {exc}")

    section("Валидное пополнение и снятие")
    active_account.deposit(Decimal("250"))
    print(f"После пополнения: {active_account}")
    active_account.withdraw(Decimal("400"))
    print(f"После снятия: {active_account}")

    section("Недостаточно средств")
    try:
        active_account.withdraw(Decimal("999999"))
    except InsufficientFundsError as exc:
        print(f"Ожидаемая ошибка: {exc}")

    section("Некорректная сумма")
    try:
        active_account.deposit(Decimal("-10"))
    except InvalidOperationError as exc:
        print(f"Ожидаемая ошибка: {exc}")

    section("get_account_info()")
    print(active_account.get_account_info())


if __name__ == "__main__":
    main()
