from collections.abc import Callable
from datetime import date, datetime, time
from decimal import Decimal

from bank.accounts import BankAccount
from bank.client import Client
from bank.enums import AccountStatus, Currency
from bank.exceptions import (
    AccountNotFoundError,
    AuthenticationError,
    ClientBlockedError,
    ClientNotFoundError,
    InvalidOperationError,
    OperationNotAllowedError,
)


class Bank:
    """
    Central bank facade managing clients and their accounts, with
    login lockout, suspicious-activity flagging and a restriction on
    operations during night hours.
    """

    NIGHT_RESTRICTION_START = time(0, 0)
    NIGHT_RESTRICTION_END = time(5, 0)

    def __init__(
        self,
        name: str,
        clock: Callable[[], datetime] = datetime.now,
        suspicious_withdrawal_threshold: Decimal = Decimal("1000000"),
    ):
        """
        Create a bank with an empty client and account registry.

        :param name: name of the bank
        :param clock: callable returning the current datetime, used
            to enforce the night-time operation restriction
        :param suspicious_withdrawal_threshold: withdrawal amount
            above which a client is flagged as suspicious
        """
        self._name = name
        self._clock = clock
        self._suspicious_withdrawal_threshold = suspicious_withdrawal_threshold
        self._clients: dict[str, Client] = {}
        self._accounts: dict[str, BankAccount] = {}
        self._account_owners: dict[str, str] = {}

    @property
    def name(self) -> str:
        """
        Get the bank's name.

        :return: bank name
        """
        return self._name

    @property
    def clients(self) -> dict[str, Client]:
        """
        Get a copy of the registered clients keyed by client id.

        :return: mapping of client id to Client
        """
        return dict(self._clients)

    @property
    def accounts(self) -> dict[str, BankAccount]:
        """
        Get a copy of the registered accounts keyed by account id.

        :return: mapping of account id to account
        """
        return dict(self._accounts)

    def _ensure_operating_hours(self, client: Client | None = None) -> None:
        """
        Reject the current operation if it falls in restricted hours,
        flagging the given client as suspicious when it does.

        :param client: client to flag if the operation is rejected
        :return: None
        """
        current_time = self._clock().time()
        in_restricted_window = (
            self.NIGHT_RESTRICTION_START
            <= current_time
            < self.NIGHT_RESTRICTION_END
        )
        if not in_restricted_window:
            return
        if client is not None:
            client.flag_suspicious(
                "Operation attempted during restricted hours "
                f"({current_time.isoformat(timespec='minutes')})"
            )
        raise OperationNotAllowedError(
            "Operations are not allowed between "
            f"{self.NIGHT_RESTRICTION_START} and "
            f"{self.NIGHT_RESTRICTION_END}"
        )

    def _get_client(self, client_id: str) -> Client:
        """
        Look up a client by id or raise if it does not exist.

        :param client_id: client identifier
        :return: the matching client
        """
        client = self._clients.get(client_id)
        if client is None:
            raise ClientNotFoundError(f"Client {client_id} not found")
        return client

    def _get_account(self, account_id: str) -> BankAccount:
        """
        Look up an account by id or raise if it does not exist.

        :param account_id: account identifier
        :return: the matching account
        """
        account = self._accounts.get(account_id)
        if account is None:
            raise AccountNotFoundError(f"Account {account_id} not found")
        return account

    def _get_client_for_account(self, account_id: str) -> Client | None:
        """
        Look up the client that owns the given account, if any.

        :param account_id: account identifier
        :return: owning client, or None if not tracked
        """
        client_id = self._account_owners.get(account_id)
        return self._clients.get(client_id) if client_id else None

    def add_client(
        self,
        full_name: str,
        birth_date: date,
        phone: str,
        email: str | None = None,
        password: str = "",
    ) -> Client:
        """
        Register a new client with the bank.

        :param full_name: client's full name
        :param birth_date: client's date of birth
        :param phone: contact phone number
        :param email: optional contact email
        :param password: password used for authentication
        :return: the created client
        """
        self._ensure_operating_hours()
        client = Client(
            full_name=full_name,
            birth_date=birth_date,
            phone=phone,
            email=email,
            password=password,
        )
        self._clients[client.client_id] = client
        return client

    def open_account(
        self,
        client_id: str,
        account_cls: type[BankAccount] = BankAccount,
        currency: Currency = Currency.RUB,
        initial_balance: Decimal = Decimal("0"),
        **extra_kwargs,
    ) -> BankAccount:
        """
        Open a new account of the given type for a client.

        :param client_id: id of the owning client
        :param account_cls: BankAccount subclass to instantiate
        :param currency: currency of the account
        :param initial_balance: starting balance of the account
        :param extra_kwargs: extra arguments forwarded to account_cls
        :return: the created account
        """
        client = self._get_client(client_id)
        self._ensure_operating_hours(client)
        if not (
            isinstance(account_cls, type)
            and issubclass(account_cls, BankAccount)
        ):
            raise InvalidOperationError(
                f"Unsupported account type: {account_cls!r}"
            )
        account = account_cls(
            owner=client.full_name,
            currency=currency,
            initial_balance=initial_balance,
            **extra_kwargs,
        )
        self._accounts[account.account_id] = account
        self._account_owners[account.account_id] = client.client_id
        client.add_account_id(account.account_id)
        return account

    def close_account(self, account_id: str) -> None:
        """
        Close an existing account.

        :param account_id: account identifier
        :return: None
        """
        account = self._get_account(account_id)
        self._ensure_operating_hours(self._get_client_for_account(account_id))
        account.close()

    def freeze_account(self, account_id: str) -> None:
        """
        Freeze an existing account.

        :param account_id: account identifier
        :return: None
        """
        account = self._get_account(account_id)
        self._ensure_operating_hours(self._get_client_for_account(account_id))
        account.freeze()

    def unfreeze_account(self, account_id: str) -> None:
        """
        Unfreeze an existing account.

        :param account_id: account identifier
        :return: None
        """
        account = self._get_account(account_id)
        self._ensure_operating_hours(self._get_client_for_account(account_id))
        account.unfreeze()

    def authenticate_client(self, client_id: str, password: str) -> bool:
        """
        Authenticate a client by password, tracking failed attempts
        and blocking the client after too many.

        :param client_id: client identifier
        :param password: password to check
        :return: True if authentication succeeded
        """
        client = self._get_client(client_id)
        self._ensure_operating_hours(client)
        if client.is_blocked:
            raise ClientBlockedError(f"Client {client_id} is blocked")
        if client.verify_password(password):
            client.record_successful_login()
            return True
        client.record_failed_login()
        if client.is_blocked:
            raise ClientBlockedError(
                f"Client {client_id} is now blocked after too many "
                f"failed login attempts"
            )
        raise AuthenticationError(f"Invalid password for client {client_id}")

    def withdraw_from_account(self, account_id: str, amount) -> None:
        """
        Withdraw funds from an account, flagging the owning client as
        suspicious if the withdrawn amount is unusually large.

        :param account_id: account identifier
        :param amount: amount to withdraw
        :return: None
        """
        account = self._get_account(account_id)
        client = self._get_client_for_account(account_id)
        self._ensure_operating_hours(client)
        balance_before = account.balance
        account.withdraw(amount)
        withdrawn = balance_before - account.balance
        if (
            client is not None
            and withdrawn > self._suspicious_withdrawal_threshold
        ):
            client.flag_suspicious(
                f"Large withdrawal of {withdrawn} from account {account_id}"
            )

    def search_accounts(
        self,
        owner: str | None = None,
        currency: Currency | None = None,
        status: AccountStatus | None = None,
        min_balance: Decimal | None = None,
        max_balance: Decimal | None = None,
    ) -> list[BankAccount]:
        """
        Search registered accounts by optional criteria.

        :param owner: case-insensitive substring of the owner's name
        :param currency: exact currency to match
        :param status: exact account status to match
        :param min_balance: minimum balance, inclusive
        :param max_balance: maximum balance, inclusive
        :return: list of matching accounts
        """
        results = list(self._accounts.values())
        if owner is not None:
            needle = owner.strip().lower()
            results = [a for a in results if needle in a.owner.lower()]
        if currency is not None:
            results = [a for a in results if a.currency == currency]
        if status is not None:
            results = [a for a in results if a.status == status]
        if min_balance is not None:
            results = [a for a in results if a.balance >= min_balance]
        if max_balance is not None:
            results = [a for a in results if a.balance <= max_balance]
        return results

    def get_total_balance(self) -> dict[Currency, Decimal]:
        """
        Get the total balance held across all accounts, per currency.

        :return: mapping of currency to total balance
        """
        totals: dict[Currency, Decimal] = {}
        for account in self._accounts.values():
            totals[account.currency] = (
                totals.get(account.currency, Decimal("0")) + account.balance
            )
        return totals

    def get_clients_ranking(self) -> list[tuple[Client, Decimal]]:
        """
        Rank clients by the combined balance of their accounts,
        descending. Balances are summed as raw numbers without
        currency conversion, which is a simplification for this
        educational model.

        :return: list of (client, total balance) pairs, descending
        """
        rankings = [
            (
                client,
                sum(
                    (
                        self._accounts[account_id].balance
                        for account_id in client.account_ids
                        if account_id in self._accounts
                    ),
                    Decimal("0"),
                ),
            )
            for client in self._clients.values()
        ]
        rankings.sort(key=lambda pair: pair[1], reverse=True)
        return rankings
