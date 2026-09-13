from decimal import Decimal

from bank.accounts.investment_account import InvestmentAccount
from bank.accounts.premium_account import PremiumAccount
from bank.accounts.savings_account import SavingsAccount
from bank.enums import AssetType, Currency
from bank.exceptions import (
    InsufficientFundsError,
    InvalidOperationError,
)

DEMO_GROWTH_RATES = {
    AssetType.STOCKS: Decimal("0.10"),
    AssetType.BONDS: Decimal("0.04"),
    AssetType.ETF: Decimal("0.07"),
}


def section(title: str) -> None:
    """
    Print a titled section separator to the console.

    :param title: section title to display
    :return: None
    """
    print(f"\n--- {title} ---")


def demo_savings_account() -> None:
    """
    Demonstrate SavingsAccount withdrawal limits and interest.

    :return: None
    """
    section("SavingsAccount")
    savings = SavingsAccount(
        owner="Anna Volkova",
        currency=Currency.RUB,
        initial_balance=Decimal("1000"),
        min_balance=Decimal("200"),
        monthly_interest_rate=Decimal("0.02"),
    )
    print(savings)

    try:
        savings.withdraw(Decimal("900"))
    except InsufficientFundsError as exc:
        print(f"Expected error: {exc}")

    savings.withdraw(Decimal("700"))
    print(f"After withdrawal: {savings}")

    interest = savings.apply_monthly_interest()
    print(f"Accrued interest: {interest}")
    print(f"After interest: {savings}")


def demo_premium_account() -> None:
    """
    Demonstrate PremiumAccount overdraft and transaction fees.

    :return: None
    """
    section("PremiumAccount")
    premium = PremiumAccount(
        owner="Oleg Sidorov",
        currency=Currency.USD,
        initial_balance=Decimal("500"),
        withdrawal_limit=Decimal("2000"),
        overdraft_limit=Decimal("300"),
        transaction_fee=Decimal("5"),
    )
    print(premium)

    premium.withdraw(Decimal("200"))
    print(f"After withdrawal with fee: {premium}")

    premium.withdraw(Decimal("580"))
    print(f"After overdraft withdrawal: {premium}")

    try:
        premium.withdraw(Decimal("50"))
    except InsufficientFundsError as exc:
        print(f"Expected error: {exc}")

    try:
        premium.withdraw(Decimal("5000"))
    except InvalidOperationError as exc:
        print(f"Expected error: {exc}")


def demo_investment_account() -> None:
    """
    Demonstrate InvestmentAccount allocation and growth projection.

    :return: None
    """
    section("InvestmentAccount")
    investment = InvestmentAccount(
        owner="Petr Kuznetsov",
        currency=Currency.EUR,
        initial_balance=Decimal("2000"),
    )
    print(investment)

    investment.invest(AssetType.STOCKS, Decimal("800"))
    investment.invest(AssetType.BONDS, Decimal("600"))
    investment.invest(AssetType.ETF, Decimal("400"))
    print(f"After allocation: {investment}")
    print(f"Portfolio: {investment.get_account_info()['portfolio']}")

    try:
        investment.withdraw(Decimal("300"))
    except InsufficientFundsError as exc:
        print(f"Expected error: {exc}")

    growth = investment.project_yearly_growth(DEMO_GROWTH_RATES)
    print(f"Projected yearly growth: {growth}")

    try:
        investment.invest("crypto", Decimal("100"))
    except InvalidOperationError as exc:
        print(f"Expected error: {exc}")


def main() -> None:
    """
    Run the day 2 demo scenarios for advanced account types.

    :return: None
    """
    demo_savings_account()
    demo_premium_account()
    demo_investment_account()


if __name__ == "__main__":
    main()
