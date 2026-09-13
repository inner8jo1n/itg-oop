from datetime import date, datetime
from decimal import Decimal

from bank.accounts.premium_account import PremiumAccount
from bank.accounts.savings_account import SavingsAccount
from bank.bank import Bank
from bank.enums import Currency
from bank.exceptions import (
    AuthenticationError,
    ClientBlockedError,
    OperationNotAllowedError,
)


def section(title: str) -> None:
    """
    Print a titled section separator to the console.

    :param title: section title to display
    :return: None
    """
    print(f"\n--- {title} ---")


def main() -> None:
    """
    Run the day 3 demo scenarios for the Bank/Client system.

    :return: None
    """
    bank = Bank(name="Demo Bank", clock=lambda: datetime(2024, 6, 1, 12, 0))

    section("Регистрация клиентов")
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
    print(anna)
    print(oleg)

    section("Открытие счетов")
    anna_savings = bank.open_account(
        anna.client_id,
        account_cls=SavingsAccount,
        currency=Currency.RUB,
        initial_balance=Decimal("10000"),
        min_balance=Decimal("1000"),
        monthly_interest_rate=Decimal("0.02"),
    )
    oleg_premium = bank.open_account(
        oleg.client_id,
        account_cls=PremiumAccount,
        currency=Currency.USD,
        initial_balance=Decimal("500"),
        overdraft_limit=Decimal("200"),
        transaction_fee=Decimal("5"),
    )
    print(anna_savings)
    print(oleg_premium)

    section("Попытки входа")
    print(
        f"Верный пароль: "
        f"{bank.authenticate_client(anna.client_id, 'anna-secret')}"
    )

    try:
        bank.authenticate_client(anna.client_id, "wrong-1")
    except AuthenticationError as exc:
        print(f"Ожидаемая ошибка: {exc}")

    try:
        bank.authenticate_client(anna.client_id, "wrong-2")
    except AuthenticationError as exc:
        print(f"Ожидаемая ошибка: {exc}")

    try:
        bank.authenticate_client(anna.client_id, "wrong-3")
    except ClientBlockedError as exc:
        print(f"Ожидаемая ошибка (блокировка): {exc}")

    print(f"Заблокирован: {anna.is_blocked}")
    print(f"Подозрительная активность: {anna.suspicious_reasons}")

    section("Заморозка счёта")
    bank.freeze_account(oleg_premium.account_id)
    print(oleg_premium)
    bank.unfreeze_account(oleg_premium.account_id)
    print(oleg_premium)

    section("Крупное снятие помечается как подозрительное")
    bank.withdraw_from_account(anna_savings.account_id, Decimal("1500"))
    print(f"Баланс после снятия: {anna_savings.balance}")

    rich_client = bank.add_client(
        full_name="Rich Client",
        birth_date=date(1980, 1, 1),
        phone="+79990000003",
        password="rich-secret",
    )
    rich_account = bank.open_account(
        rich_client.client_id, initial_balance=Decimal("2000000")
    )
    bank.withdraw_from_account(rich_account.account_id, Decimal("1500000"))
    print(f"Подозрителен ли rich_client: {rich_client.is_suspicious}")
    print(f"Причины: {rich_client.suspicious_reasons}")

    section("Запрет операций ночью (00:00-05:00)")
    night_bank = Bank(
        name="Night Bank", clock=lambda: datetime(2024, 6, 1, 2, 0)
    )
    try:
        night_bank.add_client(
            full_name="Night Owl",
            birth_date=date(1995, 1, 1),
            phone="+79990000004",
            password="owl-secret",
        )
    except OperationNotAllowedError as exc:
        print(f"Ожидаемая ошибка: {exc}")

    section("Поиск счетов")
    for found in bank.search_accounts(currency=Currency.USD):
        print(found)
    for found in bank.search_accounts(min_balance=Decimal("1000")):
        print(found)

    section("get_total_balance()")
    for currency, total in bank.get_total_balance().items():
        print(f"{currency.value}: {total}")

    section("get_clients_ranking()")
    for ranked_client, total in bank.get_clients_ranking():
        print(f"{ranked_client.full_name}: {total}")


if __name__ == "__main__":
    main()
