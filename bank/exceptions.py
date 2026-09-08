class BankError(Exception):
    pass


class AccountFrozenError(BankError):
    pass


class AccountClosedError(BankError):
    pass


class InvalidOperationError(BankError):
    pass


class InsufficientFundsError(BankError):
    pass
