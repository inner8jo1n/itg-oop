import json
from datetime import datetime

import pytest

from bank.audit.audit_log import AuditEntry, AuditLog
from bank.enums import AuditSeverity
from bank.exceptions import InvalidOperationError

DAY_TIME = datetime(2024, 1, 1, 12, 0, 0)


class TestAuditEntryCreation:
    def test_creates_entry_with_expected_fields(self):
        entry = AuditEntry(
            severity=AuditSeverity.WARNING,
            event="transaction_failed",
            message="something went wrong",
            timestamp=DAY_TIME,
            client="Ivan Ivanov",
            account_id="ACC1",
            transaction_id="TX1",
            metadata={"amount": "100"},
        )
        assert entry.severity == AuditSeverity.WARNING
        assert entry.event == "transaction_failed"
        assert entry.message == "something went wrong"
        assert entry.timestamp == DAY_TIME
        assert entry.client == "Ivan Ivanov"
        assert entry.account_id == "ACC1"
        assert entry.transaction_id == "TX1"
        assert entry.metadata == {"amount": "100"}
        assert entry.entry_id

    def test_defaults_optional_fields_to_none(self):
        entry = AuditEntry(
            severity=AuditSeverity.INFO,
            event="e",
            message="m",
            timestamp=DAY_TIME,
        )
        assert entry.client is None
        assert entry.account_id is None
        assert entry.transaction_id is None
        assert entry.metadata == {}

    def test_rejects_invalid_severity(self):
        with pytest.raises(InvalidOperationError):
            AuditEntry(
                severity="warning",
                event="e",
                message="m",
                timestamp=DAY_TIME,
            )

    def test_rejects_empty_event(self):
        with pytest.raises(InvalidOperationError):
            AuditEntry(
                severity=AuditSeverity.INFO,
                event="   ",
                message="m",
                timestamp=DAY_TIME,
            )

    def test_rejects_empty_message(self):
        with pytest.raises(InvalidOperationError):
            AuditEntry(
                severity=AuditSeverity.INFO,
                event="e",
                message="",
                timestamp=DAY_TIME,
            )

    def test_metadata_is_copied_not_aliased(self):
        source = {"key": "value"}
        entry = AuditEntry(
            severity=AuditSeverity.INFO,
            event="e",
            message="m",
            timestamp=DAY_TIME,
            metadata=source,
        )
        source["key"] = "mutated"
        assert entry.metadata == {"key": "value"}

    def test_nested_list_in_source_metadata_is_not_aliased(self):
        source = {"risk_reasons": ["large_amount"]}
        entry = AuditEntry(
            severity=AuditSeverity.INFO,
            event="e",
            message="m",
            timestamp=DAY_TIME,
            metadata=source,
        )
        source["risk_reasons"].append("mutated")
        assert entry.metadata["risk_reasons"] == ["large_amount"]

    def test_mutating_metadata_property_result_does_not_affect_entry(self):
        entry = AuditEntry(
            severity=AuditSeverity.INFO,
            event="e",
            message="m",
            timestamp=DAY_TIME,
            metadata={"risk_reasons": ["large_amount"]},
        )
        entry.metadata["risk_reasons"].append("mutated")
        assert entry.metadata["risk_reasons"] == ["large_amount"]

    def test_mutating_get_summary_metadata_does_not_affect_entry(self):
        entry = AuditEntry(
            severity=AuditSeverity.INFO,
            event="e",
            message="m",
            timestamp=DAY_TIME,
            metadata={"risk_reasons": ["large_amount"]},
        )
        entry.get_summary()["metadata"]["risk_reasons"].clear()
        assert entry.metadata["risk_reasons"] == ["large_amount"]


class TestAuditEntrySummaryAndString:
    def test_get_summary_contains_expected_fields(self):
        entry = AuditEntry(
            severity=AuditSeverity.CRITICAL,
            event="transaction_failed",
            message="blocked",
            timestamp=DAY_TIME,
            client="Ivan Ivanov",
            account_id="ACC1",
            transaction_id="TX1",
            metadata={"risk_level": "high"},
        )
        summary = entry.get_summary()
        assert summary["severity"] == "critical"
        assert summary["event"] == "transaction_failed"
        assert summary["message"] == "blocked"
        assert summary["timestamp"] == DAY_TIME.isoformat()
        assert summary["client"] == "Ivan Ivanov"
        assert summary["account_id"] == "ACC1"
        assert summary["transaction_id"] == "TX1"
        assert summary["metadata"] == {"risk_level": "high"}

    def test_str_includes_severity_and_message(self):
        entry = AuditEntry(
            severity=AuditSeverity.WARNING,
            event="e",
            message="something suspicious",
            timestamp=DAY_TIME,
        )
        text = str(entry)
        assert "WARNING" in text
        assert "something suspicious" in text


class TestAuditLogRecord:
    def test_record_appends_to_entries(self):
        log = AuditLog(clock=lambda: DAY_TIME)
        entry = log.record(severity=AuditSeverity.INFO, event="e", message="m")
        assert log.entries == [entry]

    def test_record_stamps_current_time(self):
        log = AuditLog(clock=lambda: DAY_TIME)
        entry = log.record(severity=AuditSeverity.INFO, event="e", message="m")
        assert entry.timestamp == DAY_TIME

    def test_entries_returns_a_copy(self):
        log = AuditLog(clock=lambda: DAY_TIME)
        log.record(severity=AuditSeverity.INFO, event="e", message="m")
        log.entries.clear()
        assert len(log.entries) == 1

    def test_no_file_written_when_no_path_given(self, tmp_path):
        log = AuditLog(clock=lambda: DAY_TIME)
        log.record(severity=AuditSeverity.INFO, event="e", message="m")
        assert list(tmp_path.iterdir()) == []


class TestAuditLogFilePersistence:
    def test_appends_one_json_line_per_entry(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        log = AuditLog(file_path=path, clock=lambda: DAY_TIME)
        log.record(
            severity=AuditSeverity.INFO,
            event="e1",
            message="m1",
            metadata={"amount": "100"},
        )
        log.record(severity=AuditSeverity.WARNING, event="e2", message="m2")
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["event"] == "e1"
        assert first["metadata"] == {"amount": "100"}
        second = json.loads(lines[1])
        assert second["event"] == "e2"

    def test_serializes_decimal_metadata_via_str_fallback(self, tmp_path):
        from decimal import Decimal

        path = tmp_path / "audit.jsonl"
        log = AuditLog(file_path=path, clock=lambda: DAY_TIME)
        log.record(
            severity=AuditSeverity.INFO,
            event="e",
            message="m",
            metadata={"amount": Decimal("123.45")},
        )
        line = path.read_text(encoding="utf-8").splitlines()[0]
        assert json.loads(line)["metadata"]["amount"] == "123.45"

    def test_persists_across_multiple_audit_log_instances(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        AuditLog(file_path=path, clock=lambda: DAY_TIME).record(
            severity=AuditSeverity.INFO, event="first", message="m"
        )
        AuditLog(file_path=path, clock=lambda: DAY_TIME).record(
            severity=AuditSeverity.INFO, event="second", message="m"
        )
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2


class TestAuditLogFilter:
    def _build_log(self) -> AuditLog:
        log = AuditLog(clock=lambda: DAY_TIME)
        log.record(
            severity=AuditSeverity.INFO,
            event="transaction_completed",
            message="ok",
            client="Anna",
            account_id="ACC1",
        )
        log.record(
            severity=AuditSeverity.WARNING,
            event="transaction_failed",
            message="oops",
            client="Oleg",
            account_id="ACC2",
        )
        log.record(
            severity=AuditSeverity.CRITICAL,
            event="transaction_failed",
            message="blocked",
            client="Anna",
            account_id="ACC1",
        )
        return log

    def test_filters_by_severity(self):
        log = self._build_log()
        results = log.filter(severity=AuditSeverity.WARNING)
        assert len(results) == 1
        assert results[0].message == "oops"

    def test_filters_by_event(self):
        log = self._build_log()
        results = log.filter(event="transaction_failed")
        assert len(results) == 2

    def test_filters_by_client(self):
        log = self._build_log()
        results = log.filter(client="Anna")
        assert len(results) == 2
        assert all(e.client == "Anna" for e in results)

    def test_filters_by_account_id(self):
        log = self._build_log()
        results = log.filter(account_id="ACC2")
        assert len(results) == 1

    def test_filters_by_time_range(self):
        log = AuditLog(clock=lambda: DAY_TIME)
        log.record(severity=AuditSeverity.INFO, event="e", message="m")
        assert log.filter(since=datetime(2024, 1, 1, 13, 0, 0)) == []
        assert len(log.filter(until=datetime(2024, 1, 1, 13, 0, 0))) == 1

    def test_combines_multiple_criteria(self):
        log = self._build_log()
        results = log.filter(client="Anna", severity=AuditSeverity.CRITICAL)
        assert len(results) == 1
        assert results[0].message == "blocked"

    def test_returns_empty_list_for_empty_log(self):
        log = AuditLog(clock=lambda: DAY_TIME)
        assert log.filter() == []


class TestAuditLogReports:
    def _build_log(self) -> AuditLog:
        log = AuditLog(clock=lambda: DAY_TIME)
        log.record(
            severity=AuditSeverity.INFO,
            event="transaction_completed",
            message="ok",
            client="Anna",
            metadata={"risk_reasons": []},
        )
        log.record(
            severity=AuditSeverity.WARNING,
            event="transaction_completed",
            message="flagged",
            client="Anna",
            metadata={"risk_reasons": ["new_recipient"]},
        )
        log.record(
            severity=AuditSeverity.CRITICAL,
            event="transaction_failed",
            message="blocked",
            client="Anna",
            metadata={"risk_reasons": ["large_amount", "new_recipient"]},
        )
        log.record(
            severity=AuditSeverity.WARNING,
            event="transaction_failed",
            message="insufficient funds",
            client="Oleg",
            metadata={"risk_reasons": []},
        )
        return log

    def test_suspicious_operations_report_excludes_info(self):
        log = self._build_log()
        report = log.suspicious_operations_report()
        assert len(report) == 3
        assert all(e.severity != AuditSeverity.INFO for e in report)

    def test_suspicious_operations_report_empty_when_all_info(self):
        log = AuditLog(clock=lambda: DAY_TIME)
        log.record(severity=AuditSeverity.INFO, event="e", message="m")
        assert log.suspicious_operations_report() == []

    def test_client_risk_profile_aggregates_severities_and_reasons(self):
        log = self._build_log()
        profile = log.client_risk_profile("Anna")
        assert profile["client"] == "Anna"
        assert profile["total_operations"] == 3
        assert profile["by_severity"] == {
            "info": 1,
            "warning": 1,
            "critical": 1,
        }
        assert profile["risk_reasons"] == ["large_amount", "new_recipient"]

    def test_client_risk_profile_unknown_client_is_empty(self):
        log = self._build_log()
        profile = log.client_risk_profile("Nobody")
        assert profile["total_operations"] == 0
        assert profile["risk_reasons"] == []

    def test_client_risk_profile_of_none_does_not_aggregate_everyone(self):
        # client_risk_profile's whole contract is "the profile for
        # THIS client". It's implemented as self.filter(client=client),
        # and filter()'s contract for every parameter is "None means
        # don't filter on this field" - so client=None must never
        # silently fall through to "match every entry regardless of
        # client" and report that as one client's profile. A missing/
        # unset client identifier must produce an empty profile, not
        # a leak of every other client's data under the label "None".
        log = self._build_log()
        profile = log.client_risk_profile(None)
        assert profile["total_operations"] == 0
        assert profile["by_severity"] == {
            "info": 0,
            "warning": 0,
            "critical": 0,
        }
        assert profile["risk_reasons"] == []

    def test_error_statistics_counts_by_severity_and_event(self):
        log = self._build_log()
        stats = log.error_statistics()
        assert stats["total"] == 4
        assert stats["by_severity"] == {
            "info": 1,
            "warning": 2,
            "critical": 1,
        }
        assert stats["by_event"] == {
            "transaction_completed": 2,
            "transaction_failed": 2,
        }

    def test_error_statistics_empty_log(self):
        log = AuditLog(clock=lambda: DAY_TIME)
        stats = log.error_statistics()
        assert stats == {"total": 0, "by_severity": {}, "by_event": {}}
