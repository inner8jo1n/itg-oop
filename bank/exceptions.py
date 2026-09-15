class BankError(Exception):
    """
    Base class for all bank-related errors.
    """

    pass


class AccountFrozenError(BankError):
    """
    Raised when an operation is attempted on a frozen account.
    """

    pass


class AccountClosedError(BankError):
    """
    Raised when an operation is attempted on a closed account.
    """

    pass


class InvalidOperationError(BankError):
    """
    Raised when an operation is given invalid data or arguments.
    """

    pass


class InsufficientFundsError(BankError):
    """
    Raised when a withdrawal exceeds the available balance.
    """

    pass


class ClientNotFoundError(BankError):
    """
    Raised when no client is found for the given id.
    """

    pass


class AccountNotFoundError(BankError):
    """
    Raised when no account is found for the given id.
    """

    pass


class ClientBlockedError(BankError):
    """
    Raised when an operation is attempted for a blocked client.
    """

    pass


class AuthenticationError(BankError):
    """
    Raised when authentication credentials are invalid.
    """

    pass


class OperationNotAllowedError(BankError):
    """
    Raised when an operation is attempted outside allowed hours.
    """

    pass


class TransactionNotFoundError(BankError):
    """
    Raised when no transaction is found for the given id.
    """

    pass


class ExchangeRateNotFoundError(BankError):
    """
    Raised when no exchange rate is available for a currency pair
    required by a currency conversion.
    """

    pass
