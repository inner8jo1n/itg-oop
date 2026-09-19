import copy
import json
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from bank.enums import AuditSeverity
from bank.exceptions import InvalidOperationError


class AuditEntry:
    """
    A single immutable audit record: what happened, how severe it
    is, and which client/account/transaction it concerns.
    """

    def __init__(
        self,
        severity: AuditSeverity,
        event: str,
        message: str,
        timestamp: datetime,
        client: str | None = None,
        account_id: str | None = None,
        transaction_id: str | None = None,
        metadata: dict | None = None,
        entry_id: str | None = None,
    ):
        """
        Create an audit entry.

        :param severity: importance level of this entry
        :param event: short machine-readable event name, e.g.
            "transaction_completed"
        :param message: human-readable description
        :param timestamp: time the event occurred
        :param client: human-readable identifier of the client this
            entry concerns; TransactionProcessor populates this from
            the account owner's name, since it has no access to the
            Bank's client registry
        :param account_id: id of the account this entry concerns
        :param transaction_id: id of the transaction this entry
            concerns, if any
        :param metadata: arbitrary extra structured data
        :param entry_id: identifier, auto-generated if not given
        """
        if not isinstance(severity, AuditSeverity):
            raise InvalidOperationError(f"Unsupported severity: {severity!r}")
        if not event or not str(event).strip():
            raise InvalidOperationError("Event must not be empty")
        if not message or not str(message).strip():
            raise InvalidOperationError("Message must not be empty")

        self._entry_id = (
            str(entry_id).strip() if entry_id else self._generate_entry_id()
        )
        self._severity = severity
        self._event = str(event).strip()
        self._message = str(message).strip()
        self._timestamp = timestamp
        self._client = client
        self._account_id = account_id
        self._transaction_id = transaction_id
        self._metadata = copy.deepcopy(dict(metadata or {}))

    @staticmethod
    def _generate_entry_id() -> str:
        """
        Generate a short unique entry identifier.

        :return: generated entry identifier
        """
        return uuid.uuid4().hex[:12].upper()

    @property
    def entry_id(self) -> str:
        """
        Get the unique entry identifier.

        :return: entry identifier
        """
        return self._entry_id

    @property
    def severity(self) -> AuditSeverity:
        """
        Get the importance level of this entry.

        :return: entry severity
        """
        return self._severity

    @property
    def event(self) -> str:
        """
        Get the short machine-readable event name.

        :return: event name
        """
        return self._event

    @property
    def message(self) -> str:
        """
        Get the human-readable description.

        :return: entry message
        """
        return self._message

    @property
    def timestamp(self) -> datetime:
        """
        Get the time the event occurred.

        :return: entry timestamp
        """
        return self._timestamp

    @property
    def client(self) -> str | None:
        """
        Get the human-readable client identifier, if any.

        :return: client identifier or None
        """
        return self._client

    @property
    def account_id(self) -> str | None:
        """
        Get the id of the account this entry concerns, if any.

        :return: account id or None
        """
        return self._account_id

    @property
    def transaction_id(self) -> str | None:
        """
        Get the id of the transaction this entry concerns, if any.

        :return: transaction id or None
        """
        return self._transaction_id

    @property
    def metadata(self) -> dict:
        """
        Get a deep copy of the entry's extra structured data, so
        mutating a nested list or dict in the result can never
        affect this entry's real stored state.

        :return: metadata dictionary
        """
        return copy.deepcopy(self._metadata)

    def get_summary(self) -> dict:
        """
        Get a summary of the entry's data, with JSON-serializable
        values (timestamp as ISO 8601, severity as its raw value).
        The metadata is deep-copied for the same reason as the
        `metadata` property.

        :return: dictionary with all entry fields
        """
        return {
            "entry_id": self._entry_id,
            "severity": self._severity.value,
            "event": self._event,
            "message": self._message,
            "timestamp": self._timestamp.isoformat(),
            "client": self._client,
            "account_id": self._account_id,
            "transaction_id": self._transaction_id,
            "metadata": copy.deepcopy(self._metadata),
        }

    def __str__(self) -> str:
        """
        Build a human-readable representation of the entry.

        :return: string with severity, event, timestamp and message
        """
        return (
            f"[{self._severity.value.upper()}] "
            f"{self._timestamp.isoformat(timespec='seconds')} | "
            f"{self._event} | {self._message}"
        )


class AuditLog:
    """
    Records audit entries in memory and, optionally, appends them as
    JSON lines to a file. Supports filtering and a few standard
    security reports built on top of the recorded entries.
    """

    def __init__(
        self,
        file_path: str | Path | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ):
        """
        Create an audit log.

        :param file_path: path to append JSON-lines audit records
            to; if None, entries are kept in memory only
        :param clock: callable returning the current datetime, used
            to stamp new entries
        """
        self._file_path = Path(file_path) if file_path else None
        self._clock = clock
        self._entries: list[AuditEntry] = []

    @property
    def entries(self) -> list[AuditEntry]:
        """
        Get a copy of all recorded entries, oldest first.

        :return: list of audit entries
        """
        return list(self._entries)

    def record(
        self,
        severity: AuditSeverity,
        event: str,
        message: str,
        client: str | None = None,
        account_id: str | None = None,
        transaction_id: str | None = None,
        metadata: dict | None = None,
    ) -> AuditEntry:
        """
        Create and store a new audit entry, appending it to the
        backing file if one was configured.

        :param severity: importance level of this entry
        :param event: short machine-readable event name
        :param message: human-readable description
        :param client: human-readable client identifier, if any
        :param account_id: id of the account this entry concerns
        :param transaction_id: id of the transaction this entry
            concerns, if any
        :param metadata: arbitrary extra structured data
        :return: the created audit entry
        """
        entry = AuditEntry(
            severity=severity,
            event=event,
            message=message,
            timestamp=self._clock(),
            client=client,
            account_id=account_id,
            transaction_id=transaction_id,
            metadata=metadata,
        )
        self._entries.append(entry)
        if self._file_path is not None:
            self._append_to_file(entry)
        return entry

    def _append_to_file(self, entry: AuditEntry) -> None:
        """
        Append a single entry to the backing file as one JSON line.

        :param entry: entry to persist
        :return: None
        """
        line = json.dumps(entry.get_summary(), ensure_ascii=False, default=str)
        with self._file_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def filter(
        self,
        severity: AuditSeverity | None = None,
        event: str | None = None,
        client: str | None = None,
        account_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[AuditEntry]:
        """
        Filter recorded entries by any combination of criteria.

        :param severity: exact severity to match
        :param event: exact event name to match
        :param client: exact client identifier to match
        :param account_id: exact account id to match
        :param since: minimum timestamp, inclusive
        :param until: maximum timestamp, inclusive
        :return: list of matching entries, oldest first
        """
        results = list(self._entries)
        if severity is not None:
            results = [e for e in results if e.severity == severity]
        if event is not None:
            results = [e for e in results if e.event == event]
        if client is not None:
            results = [e for e in results if e.client == client]
        if account_id is not None:
            results = [e for e in results if e.account_id == account_id]
        if since is not None:
            results = [e for e in results if e.timestamp >= since]
        if until is not None:
            results = [e for e in results if e.timestamp <= until]
        return results

    def suspicious_operations_report(self) -> list[AuditEntry]:
        """
        Get all entries actually flagged by risk analysis, i.e. ones
        whose metadata records at least one triggered risk reason.
        Severity is deliberately not used for this: an entry can be
        WARNING purely from an ordinary business failure (e.g.
        insufficient funds) with zero risk factors, which is a
        failure, not a suspicious operation.

        :return: entries with at least one risk reason, oldest first
        """
        return [
            entry
            for entry in self._entries
            if entry.metadata.get("risk_reasons")
        ]

    def client_risk_profile(self, client: str) -> dict:
        """
        Summarize a client's audit history.

        Deliberately does not delegate to filter(client=client):
        filter()'s contract treats None as "don't filter on this
        field", which would make client_risk_profile(None) silently
        aggregate every client's entries under the label "None".
        Here, client identifies which single profile to build, so
        it is always matched by exact equality, including when it
        is None.

        :param client: client identifier to build the profile for
        :return: dictionary with total entry count, counts by
            severity, and the distinct risk reasons seen in this
            client's entries' metadata (under the "risk_reasons" key)
        """
        client_entries = [e for e in self._entries if e.client == client]
        by_severity = {severity: 0 for severity in AuditSeverity}
        risk_reasons: set[str] = set()
        for entry in client_entries:
            by_severity[entry.severity] += 1
            risk_reasons.update(entry.metadata.get("risk_reasons") or [])
        return {
            "client": client,
            "total_operations": len(client_entries),
            "by_severity": {
                severity.value: count
                for severity, count in by_severity.items()
            },
            "risk_reasons": sorted(risk_reasons),
        }

    def error_statistics(self) -> dict:
        """
        Summarize failed/blocked entries only, by severity and event
        name. An entry counts as a failure when its metadata's
        "success" key is explicitly False; entries that never set
        that key, or set it True, are excluded, so an ordinary
        successful entry (e.g. transaction_completed) can never be
        miscounted as an error just because of its severity or name.

        :return: dictionary with total failure count, counts by
            severity, and counts by event name - restricted to
            failed/blocked entries
        """
        failures = [
            entry
            for entry in self._entries
            if entry.metadata.get("success") is False
        ]
        by_severity: dict[str, int] = {}
        by_event: dict[str, int] = {}
        for entry in failures:
            by_severity[entry.severity.value] = (
                by_severity.get(entry.severity.value, 0) + 1
            )
            by_event[entry.event] = by_event.get(entry.event, 0) + 1
        return {
            "total": len(failures),
            "by_severity": by_severity,
            "by_event": by_event,
        }
