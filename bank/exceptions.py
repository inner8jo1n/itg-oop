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
