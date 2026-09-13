from decimal import Decimal

import pytest

from bank.accounts.investment_account import InvestmentAccount
from bank.enums import AssetType
from bank.exceptions import InsufficientFundsError, InvalidOperationError


class TestInvestmentAccountCreation:
    def test_fresh_account_starts_with_zero_portfolio(
        self, investment_account: InvestmentAccount
    ):
        assert investment_account.portfolio == {
            AssetType.STOCKS: Decimal("0"),
            AssetType.BONDS: Decimal("0"),
            AssetType.ETF: Decimal("0"),
        }
        assert investment_account.portfolio_value == Decimal("0")


class TestInvestmentAccountInvest:
    def test_moves_funds_into_portfolio(
        self, investment_account: InvestmentAccount
    ):
        investment_account.invest(AssetType.STOCKS, Decimal("400"))
        assert investment_account.balance == Decimal("600")
        assert investment_account.portfolio[AssetType.STOCKS] == Decimal("400")
        assert investment_account.portfolio_value == Decimal("400")

    def test_tracks_multiple_asset_types_independently(
        self, investment_account: InvestmentAccount
    ):
        investment_account.invest(AssetType.STOCKS, Decimal("300"))
        investment_account.invest(AssetType.BONDS, Decimal("200"))
        assert investment_account.portfolio[AssetType.STOCKS] == Decimal("300")
        assert investment_account.portfolio[AssetType.BONDS] == Decimal("200")
        assert investment_account.portfolio[AssetType.ETF] == Decimal("0")

    def test_accumulates_repeated_investment_into_same_asset(
        self, investment_account: InvestmentAccount
    ):
        investment_account.invest(AssetType.STOCKS, Decimal("100"))
        investment_account.invest(AssetType.STOCKS, Decimal("100"))
        assert investment_account.portfolio[AssetType.STOCKS] == Decimal("200")

    def test_portfolio_property_returns_defensive_copy(
        self, investment_account: InvestmentAccount
    ):
        investment_account.invest(AssetType.STOCKS, Decimal("100"))
        snapshot = investment_account.portfolio
        snapshot[AssetType.STOCKS] = Decimal("999999")
        assert investment_account.portfolio[AssetType.STOCKS] == Decimal("100")

    def test_allows_investing_entire_balance(
        self, investment_account: InvestmentAccount
    ):
        investment_account.invest(AssetType.STOCKS, investment_account.balance)
        assert investment_account.balance == Decimal("0")

    def test_rejects_invalid_asset_type(
        self, investment_account: InvestmentAccount
    ):
        with pytest.raises(InvalidOperationError):
            investment_account.invest("crypto", Decimal("100"))

    def test_rejects_plain_string_matching_asset_value(
        self, investment_account: InvestmentAccount
    ):
        with pytest.raises(InvalidOperationError):
            investment_account.invest("stocks", Decimal("100"))

    def test_rejects_non_positive_amount(
        self, investment_account: InvestmentAccount
    ):
        with pytest.raises(InvalidOperationError):
            investment_account.invest(AssetType.BONDS, Decimal("0"))

    def test_rejects_negative_amount(
        self, investment_account: InvestmentAccount
    ):
        with pytest.raises(InvalidOperationError):
            investment_account.invest(AssetType.BONDS, Decimal("-50"))

    def test_rejects_invalid_amount_type(
        self, investment_account: InvestmentAccount
    ):
        with pytest.raises(InvalidOperationError):
            investment_account.invest(AssetType.BONDS, "not-a-number")

    def test_rejects_insufficient_funds(
        self, investment_account: InvestmentAccount
    ):
        with pytest.raises(InsufficientFundsError):
            investment_account.invest(AssetType.ETF, Decimal("99999"))


class TestInvestmentAccountWithdraw:
    def test_withdraws_from_cash_only(
        self, investment_account: InvestmentAccount
    ):
        investment_account.invest(AssetType.STOCKS, Decimal("700"))
        investment_account.withdraw(Decimal("300"))
        assert investment_account.balance == Decimal("0")

    def test_rejects_withdrawal_of_invested_funds(
        self, investment_account: InvestmentAccount
    ):
        investment_account.invest(AssetType.STOCKS, Decimal("700"))
        with pytest.raises(InsufficientFundsError):
            investment_account.withdraw(Decimal("301"))


class TestInvestmentAccountProjectGrowth:
    def test_computes_projected_growth(
        self, investment_account: InvestmentAccount
    ):
        investment_account.invest(AssetType.STOCKS, Decimal("500"))
        investment_account.invest(AssetType.BONDS, Decimal("300"))
        investment_account.invest(AssetType.ETF, Decimal("200"))
        growth = investment_account.project_yearly_growth(
            {
                AssetType.STOCKS: Decimal("0.10"),
                AssetType.BONDS: Decimal("0.04"),
                AssetType.ETF: Decimal("0.07"),
            }
        )
        assert growth == Decimal("50.00") + Decimal("12.00") + Decimal("14.00")

    def test_rejects_invalid_asset_type_in_growth_rates(
        self, investment_account: InvestmentAccount
    ):
        with pytest.raises(InvalidOperationError):
            investment_account.project_yearly_growth({"crypto": 0.5})

    def test_partial_growth_rates_ignores_unmentioned_assets(
        self, investment_account: InvestmentAccount
    ):
        investment_account.invest(AssetType.STOCKS, Decimal("500"))
        investment_account.invest(AssetType.BONDS, Decimal("300"))
        growth = investment_account.project_yearly_growth(
            {AssetType.STOCKS: Decimal("0.10")}
        )
        assert growth == Decimal("50.00")

    def test_empty_growth_rates_returns_zero(
        self, investment_account: InvestmentAccount
    ):
        investment_account.invest(AssetType.STOCKS, Decimal("500"))
        assert investment_account.project_yearly_growth({}) == Decimal("0")

    def test_is_side_effect_free(self, investment_account: InvestmentAccount):
        investment_account.invest(AssetType.STOCKS, Decimal("500"))
        balance_before = investment_account.balance
        portfolio_before = investment_account.portfolio
        investment_account.project_yearly_growth(
            {AssetType.STOCKS: Decimal("0.10")}
        )
        assert investment_account.balance == balance_before
        assert investment_account.portfolio == portfolio_before

    def test_allows_negative_rate_for_loss_projection(
        self, investment_account: InvestmentAccount
    ):
        investment_account.invest(AssetType.STOCKS, Decimal("500"))
        growth = investment_account.project_yearly_growth(
            {AssetType.STOCKS: Decimal("-0.10")}
        )
        assert growth == Decimal("-50.00")

    def test_rejects_non_numeric_rate(
        self, investment_account: InvestmentAccount
    ):
        investment_account.invest(AssetType.STOCKS, Decimal("500"))
        with pytest.raises(InvalidOperationError):
            investment_account.project_yearly_growth(
                {AssetType.STOCKS: "not-a-number"}
            )

    def test_rejects_nan_rate(self, investment_account: InvestmentAccount):
        investment_account.invest(AssetType.STOCKS, Decimal("500"))
        with pytest.raises(InvalidOperationError):
            investment_account.project_yearly_growth(
                {AssetType.STOCKS: float("nan")}
            )

    def test_rejects_infinite_rate(
        self, investment_account: InvestmentAccount
    ):
        investment_account.invest(AssetType.STOCKS, Decimal("500"))
        with pytest.raises(InvalidOperationError):
            investment_account.project_yearly_growth(
                {AssetType.STOCKS: float("inf")}
            )


class TestInvestmentAccountPolymorphism:
    def test_get_account_info_contains_portfolio(
        self, investment_account: InvestmentAccount
    ):
        investment_account.invest(AssetType.STOCKS, Decimal("100"))
        info = investment_account.get_account_info()
        assert info["portfolio"]["stocks"] == Decimal("100")
        assert info["portfolio_value"] == Decimal("100")

    def test_str_contains_portfolio_value(
        self, investment_account: InvestmentAccount
    ):
        text = str(investment_account)
        assert "Portfolio value" in text
