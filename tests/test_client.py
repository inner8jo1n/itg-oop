from datetime import date

import pytest

from bank.client import Client
from bank.enums import ClientStatus
from bank.exceptions import InvalidOperationError


class TestClientCreation:
    def test_creates_active_client(self, adult_birth_date: date):
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
        )
        assert client.full_name == "Ivan Ivanov"
        assert client.status == ClientStatus.ACTIVE
        assert client.account_ids == []
        assert client.client_id

    def test_rejects_empty_full_name(self, adult_birth_date: date):
        with pytest.raises(InvalidOperationError):
            Client(
                full_name="   ",
                birth_date=adult_birth_date,
                phone="+79990000000",
                password="secret123",
            )

    def test_rejects_empty_phone(self, adult_birth_date: date):
        with pytest.raises(InvalidOperationError):
            Client(
                full_name="Ivan Ivanov",
                birth_date=adult_birth_date,
                phone="  ",
                password="secret123",
            )

    def test_rejects_empty_password(self, adult_birth_date: date):
        with pytest.raises(InvalidOperationError):
            Client(
                full_name="Ivan Ivanov",
                birth_date=adult_birth_date,
                phone="+79990000000",
                password="",
            )

    def test_rejects_non_date_birth_date(self):
        with pytest.raises(InvalidOperationError):
            Client(
                full_name="Ivan Ivanov",
                birth_date="2000-01-01",
                phone="+79990000000",
                password="secret123",
            )

    def test_rejects_client_under_18(self):
        today = date.today()
        underage_birth_date = today.replace(year=today.year - 17)
        with pytest.raises(InvalidOperationError):
            Client(
                full_name="Ivan Ivanov",
                birth_date=underage_birth_date,
                phone="+79990000000",
                password="secret123",
            )

    def test_accepts_client_exactly_18(self):
        today = date.today()
        exactly_18_birth_date = today.replace(year=today.year - 18)
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=exactly_18_birth_date,
            phone="+79990000000",
            password="secret123",
        )
        assert client.age == 18

    def test_rejects_future_birth_date(self):
        today = date.today()
        future_birth_date = today.replace(year=today.year + 1)
        with pytest.raises(InvalidOperationError):
            Client(
                full_name="Ivan Ivanov",
                birth_date=future_birth_date,
                phone="+79990000000",
                password="secret123",
            )

    def test_full_name_is_trimmed_and_stored(self, adult_birth_date: date):
        client = Client(
            full_name="  Ivan Ivanov  ",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
        )
        assert client.full_name == "Ivan Ivanov"

    def test_coerces_non_string_full_name_to_str(self, adult_birth_date: date):
        client = Client(
            full_name=12345,
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
        )
        assert client.full_name == "12345"
        assert isinstance(client.full_name, str)

    def test_accepts_explicit_client_id(self, adult_birth_date: date):
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
            client_id="CUSTOM-ID",
        )
        assert client.client_id == "CUSTOM-ID"

    def test_strips_whitespace_from_client_id(self, adult_birth_date: date):
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
            client_id=" CUSTOM-ID ",
        )
        assert client.client_id == "CUSTOM-ID"

    def test_falsy_client_id_triggers_autogeneration(
        self, adult_birth_date: date
    ):
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
            client_id="",
        )
        assert client.client_id

    def test_phone_and_email_are_stored(self, adult_birth_date: date):
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            email="ivan@example.com",
            password="secret123",
        )
        assert client.phone == "+79990000000"
        assert client.email == "ivan@example.com"

    def test_default_email_is_none(self, adult_birth_date: date):
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
        )
        assert client.email is None

    def test_whitespace_only_email_is_stored_as_empty_string(
        self, adult_birth_date: date
    ):
        # Characterizes current behavior: unlike full_name/phone,
        # whitespace-only email is not rejected, it collapses to "".
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            email="   ",
            password="secret123",
        )
        assert client.email == ""


class TestClientAuthentication:
    def test_fresh_client_is_not_blocked(self, adult_birth_date: date):
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
        )
        assert client.is_blocked is False

    def test_verify_password_matches(self, adult_birth_date: date):
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
        )
        assert client.verify_password("secret123") is True
        assert client.verify_password("wrong") is False

    def test_successful_login_resets_failed_attempts(
        self, adult_birth_date: date
    ):
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
        )
        client.record_failed_login()
        client.record_failed_login()
        client.record_successful_login()
        assert client.failed_login_attempts == 0

    def test_reset_allowance_is_renewable(self, adult_birth_date: date):
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
        )
        client.record_failed_login()
        client.record_failed_login()
        client.record_successful_login()
        client.record_failed_login()
        client.record_failed_login()
        assert client.is_blocked is False
        client.record_failed_login()
        assert client.is_blocked is True

    def test_blocks_after_three_failed_attempts(self, adult_birth_date: date):
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
        )
        client.record_failed_login()
        client.record_failed_login()
        assert client.status == ClientStatus.ACTIVE
        client.record_failed_login()
        assert client.is_blocked
        assert client.is_suspicious
        assert client.suspicious_reasons


class TestClientAccounts:
    def test_add_account_id_appends(self, adult_birth_date: date):
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
        )
        client.add_account_id("ACC1")
        client.add_account_id("ACC2")
        assert client.account_ids == ["ACC1", "ACC2"]

    def test_account_ids_returns_defensive_copy(self, adult_birth_date: date):
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
        )
        client.add_account_id("ACC1")
        snapshot = client.account_ids
        snapshot.append("ACC2")
        assert client.account_ids == ["ACC1"]

    def test_add_account_id_allows_duplicates(self, adult_birth_date: date):
        # Characterizes current behavior: no dedup check is performed.
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
        )
        client.add_account_id("ACC1")
        client.add_account_id("ACC1")
        assert client.account_ids == ["ACC1", "ACC1"]


class TestClientSuspiciousActivity:
    def test_flag_suspicious_records_reason(self, adult_birth_date: date):
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
        )
        assert client.is_suspicious is False
        client.flag_suspicious("unusual activity")
        assert client.is_suspicious is True
        assert "unusual activity" in client.suspicious_reasons

    def test_flag_suspicious_does_not_block_client(
        self, adult_birth_date: date
    ):
        client = Client(
            full_name="Ivan Ivanov",
            birth_date=adult_birth_date,
            phone="+79990000000",
            password="secret123",
        )
        client.flag_suspicious("unusual activity")
        assert client.status == ClientStatus.ACTIVE
        assert client.is_blocked is False
