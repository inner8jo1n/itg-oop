import uuid
from datetime import date

from bank.enums import ClientStatus
from bank.exceptions import InvalidOperationError

MIN_CLIENT_AGE = 18
MAX_FAILED_LOGIN_ATTEMPTS = 3


class Client:
    """
    Bank client: identity, contact details, owned account ids and
    authentication/security state.
    """

    def __init__(
        self,
        full_name: str,
        birth_date: date,
        phone: str,
        email: str | None = None,
        password: str = "",
        client_id: str | None = None,
    ):
        """
        Create a client, validating identity, contacts and age.

        :param full_name: client's full name
        :param birth_date: client's date of birth
        :param phone: contact phone number
        :param email: optional contact email
        :param password: password used for authentication
        :param client_id: client identifier, auto-generated if not
            given
        """
        if not full_name or not str(full_name).strip():
            raise InvalidOperationError("Full name must not be empty")
        if not isinstance(birth_date, date):
            raise InvalidOperationError(
                f"Birth date must be a date, got {birth_date!r}"
            )
        if not phone or not str(phone).strip():
            raise InvalidOperationError("Phone must not be empty")
        if not password:
            raise InvalidOperationError("Password must not be empty")

        age = self._calculate_age(birth_date)
        if age < MIN_CLIENT_AGE:
            raise InvalidOperationError(
                f"Client must be at least {MIN_CLIENT_AGE} years old, "
                f"got {age}"
            )

        self._client_id = (
            str(client_id).strip() if client_id else self._generate_client_id()
        )
        self._full_name = str(full_name).strip()
        self._birth_date = birth_date
        self._phone = str(phone).strip()
        self._email = str(email).strip() if email else None
        self._password = password
        self._status = ClientStatus.ACTIVE
        self._account_ids: list[str] = []
        self._failed_login_attempts = 0
        self._suspicious_reasons: list[str] = []

    @staticmethod
    def _generate_client_id() -> str:
        """
        Generate a short unique client identifier.

        :return: generated client identifier
        """
        return uuid.uuid4().hex[:12].upper()

    @staticmethod
    def _calculate_age(birth_date: date) -> int:
        """
        Calculate age in full years as of today.

        :param birth_date: date of birth
        :return: age in years
        """
        today = date.today()
        had_birthday = (today.month, today.day) >= (
            birth_date.month,
            birth_date.day,
        )
        return today.year - birth_date.year - (0 if had_birthday else 1)

    @property
    def client_id(self) -> str:
        """
        Get the unique client identifier.

        :return: client identifier
        """
        return self._client_id

    @property
    def full_name(self) -> str:
        """
        Get the client's full name.

        :return: full name
        """
        return self._full_name

    @property
    def phone(self) -> str:
        """
        Get the client's contact phone number.

        :return: phone number
        """
        return self._phone

    @property
    def email(self) -> str | None:
        """
        Get the client's contact email, if provided.

        :return: email or None
        """
        return self._email

    @property
    def age(self) -> int:
        """
        Get the client's current age in years.

        :return: age in years
        """
        return self._calculate_age(self._birth_date)

    @property
    def status(self) -> ClientStatus:
        """
        Get the client's current authentication status.

        :return: client status
        """
        return self._status

    @property
    def is_blocked(self) -> bool:
        """
        Check whether the client is blocked from authenticating.

        :return: True if blocked, False otherwise
        """
        return self._status == ClientStatus.BLOCKED

    @property
    def account_ids(self) -> list[str]:
        """
        Get a copy of the ids of accounts owned by this client.

        :return: list of account ids
        """
        return list(self._account_ids)

    @property
    def failed_login_attempts(self) -> int:
        """
        Get the current count of consecutive failed login attempts.

        :return: number of failed login attempts
        """
        return self._failed_login_attempts

    @property
    def is_suspicious(self) -> bool:
        """
        Check whether any suspicious activity has been flagged.

        :return: True if at least one reason was flagged
        """
        return bool(self._suspicious_reasons)

    @property
    def suspicious_reasons(self) -> list[str]:
        """
        Get a copy of the recorded suspicious-activity reasons.

        :return: list of reasons
        """
        return list(self._suspicious_reasons)

    def add_account_id(self, account_id: str) -> None:
        """
        Register an account id as owned by this client.

        :param account_id: account identifier to add
        :return: None
        """
        self._account_ids.append(account_id)

    def verify_password(self, password: str) -> bool:
        """
        Check whether the given password matches the stored one.

        :param password: password to check
        :return: True if it matches, False otherwise
        """
        return password == self._password

    def record_successful_login(self) -> None:
        """
        Reset the failed login attempt counter after a success.

        :return: None
        """
        self._failed_login_attempts = 0

    def record_failed_login(self) -> None:
        """
        Record a failed login attempt, blocking the client and
        flagging suspicious activity once the limit is reached.

        :return: None
        """
        self._failed_login_attempts += 1
        if self._failed_login_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
            self._status = ClientStatus.BLOCKED
            self.flag_suspicious(
                f"{MAX_FAILED_LOGIN_ATTEMPTS} consecutive failed "
                f"login attempts"
            )

    def flag_suspicious(self, reason: str) -> None:
        """
        Record a reason this client was flagged as suspicious.

        :param reason: description of the suspicious activity
        :return: None
        """
        self._suspicious_reasons.append(reason)

    def __str__(self) -> str:
        """
        Build a human-readable representation of the client.

        :return: string with name, id, status and account count
        """
        return (
            f"Client | {self._full_name} | ID: {self._client_id} | "
            f"Status: {self._status.value} | "
            f"Accounts: {len(self._account_ids)}"
        )
