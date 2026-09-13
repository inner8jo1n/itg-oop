from decimal import Decimal, InvalidOperation
from typing import override

from bank.accounts.bank_account import BankAccount
from bank.enums import AssetType, Currency
from bank.exceptions import InsufficientFundsError, InvalidOperationError


class InvestmentAccount(BankAccount):
    """
    Bank account that can allocate part of its cash balance into a
    virtual investment portfolio spread across asset types.
    """

    def __init__(
        self,
        owner: str,
        currency: Currency = Currency.RUB,
        account_id: str | None = None,
        initial_balance: Decimal = Decimal("0"),
    ):
        """
        Create an investment account with an empty portfolio.

        :param owner: name of the account owner
        :param currency: currency of the account
        :param account_id: account identifier, auto-generated if not
            given
        :param initial_balance: starting cash balance of the account
        """
        super().__init__(
            owner=owner,
            currency=currency,
            account_id=account_id,
            initial_balance=initial_balance,
        )
        self._portfolio: dict[AssetType, Decimal] = {
            asset_type: Decimal("0") for asset_type in AssetType
        }

    @property
    def portfolio(self) -> dict[AssetType, Decimal]:
        """
        Get a copy of the current asset allocation.

        :return: mapping of asset type to invested amount
        """
        return dict(self._portfolio)

    @property
    def portfolio_value(self) -> Decimal:
        """
        Get the total amount currently invested across all assets.

        :return: sum of all portfolio allocations
        """
        return sum(self._portfolio.values(), Decimal("0"))

    def invest(self, asset_type: AssetType, amount) -> None:
        """
        Move funds from the cash balance into a portfolio asset type.

        :param asset_type: target asset type
        :param amount: amount to invest
        :return: None
        """
        self._ensure_operable()
        if not isinstance(asset_type, AssetType):
            raise InvalidOperationError(
                f"Unsupported asset type: {asset_type!r}"
            )
        validated = self._validate_amount(amount)
        if validated > self._balance:
            raise InsufficientFundsError(
                f"Insufficient funds on {self._account_id}: balance "
                f"{self._balance}, requested {validated}"
            )
        self._balance -= validated
        self._portfolio[asset_type] += validated

    @override
    def withdraw(self, amount) -> None:
        """
        Remove funds from the cash balance; invested portfolio funds
        are not directly withdrawable.

        :param amount: amount to withdraw
        :return: None
        """
        self._ensure_operable()
        validated = self._validate_amount(amount)
        if validated > self._balance:
            raise InsufficientFundsError(
                f"Insufficient cash on {self._account_id}: available "
                f"{self._balance}, requested {validated} (portfolio "
                f"funds are invested and not directly withdrawable)"
            )
        self._balance -= validated

    def project_yearly_growth(self, growth_rates: dict) -> Decimal:
        """
        Estimate the yearly growth of the portfolio given annual
        growth rates per asset type.

        :param growth_rates: mapping of asset type to annual growth
            rate, e.g. {AssetType.STOCKS: Decimal("0.10")}
        :return: projected total growth amount
        """
        total_growth = Decimal("0")
        for asset_type, rate in growth_rates.items():
            if not isinstance(asset_type, AssetType):
                raise InvalidOperationError(
                    f"Unsupported asset type: {asset_type!r}"
                )
            total_growth += self._portfolio[asset_type] * (
                self._validate_rate(rate)
            )
        return total_growth

    @staticmethod
    def _validate_rate(rate) -> Decimal:
        """
        Validate and convert a growth rate to a finite Decimal.

        :param rate: value to validate
        :return: validated rate as Decimal
        """
        try:
            validated = Decimal(str(rate))
        except (InvalidOperation, TypeError, ValueError) as err:
            raise InvalidOperationError(
                f"Growth rate must be a number, got {rate!r}"
            ) from err
        if validated.is_nan() or validated.is_infinite():
            raise InvalidOperationError(
                f"Growth rate must be finite, got {rate!r}"
            )
        return validated

    @override
    def get_account_info(self) -> dict:
        """
        Get a summary of the investment account's data.

        :return: base account info plus portfolio breakdown and
            total portfolio value
        """
        info = super().get_account_info()
        info.update(
            {
                "portfolio": {
                    asset_type.value: amount
                    for asset_type, amount in self._portfolio.items()
                },
                "portfolio_value": self.portfolio_value,
            }
        )
        return info

    @override
    def __str__(self) -> str:
        """
        Build a human-readable representation of the account.

        :return: base representation with total portfolio value
        """
        return (
            f"{super().__str__()} | Portfolio value: "
            f"{self.portfolio_value} {self._currency.value}"
        )
