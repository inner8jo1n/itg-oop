from datetime import datetime

from bank.enums import ReportType
from bank.exceptions import InvalidOperationError


class Report:
    """
    A generated report: a title and summary, plus a uniform list of
    row dicts (all sharing the same field names) suitable for
    tabular export. Immutable once built.
    """

    def __init__(
        self,
        report_type: ReportType,
        title: str,
        generated_at: datetime,
        summary: dict,
        fieldnames: list[str],
        rows: list[dict],
    ):
        """
        Create a report.

        :param report_type: kind of report this is
        :param title: human-readable title
        :param generated_at: time the report was built
        :param summary: arbitrary key -> value overview data
        :param fieldnames: column names every row dict must use, in
            display order; fixed up front so CSV export has stable
            headers even when rows is empty
        :param rows: list of row dicts, each using exactly the keys
            in fieldnames
        """
        if not isinstance(report_type, ReportType):
            raise InvalidOperationError(
                f"Unsupported report type: {report_type!r}"
            )
        if not title or not str(title).strip():
            raise InvalidOperationError("Title must not be empty")
        if not fieldnames:
            raise InvalidOperationError("Fieldnames must not be empty")
        field_set = set(fieldnames)
        for row in rows:
            if set(row.keys()) != field_set:
                raise InvalidOperationError(
                    f"Row keys {sorted(row.keys())} do not match "
                    f"fieldnames {sorted(field_set)}"
                )

        self._report_type = report_type
        self._title = str(title).strip()
        self._generated_at = generated_at
        self._summary = dict(summary)
        self._fieldnames = list(fieldnames)
        self._rows = [dict(row) for row in rows]

    @property
    def report_type(self) -> ReportType:
        """
        Get the kind of report this is.

        :return: report type
        """
        return self._report_type

    @property
    def title(self) -> str:
        """
        Get the human-readable title.

        :return: report title
        """
        return self._title

    @property
    def generated_at(self) -> datetime:
        """
        Get the time the report was built.

        :return: generation timestamp
        """
        return self._generated_at

    @property
    def summary(self) -> dict:
        """
        Get a copy of the report's overview data.

        :return: summary dictionary
        """
        return dict(self._summary)

    @property
    def fieldnames(self) -> list[str]:
        """
        Get a copy of the row column names, in display order.

        :return: list of field names
        """
        return list(self._fieldnames)

    @property
    def rows(self) -> list[dict]:
        """
        Get a copy of the report's tabular rows.

        :return: list of row dicts
        """
        return [dict(row) for row in self._rows]

    def to_dict(self) -> dict:
        """
        Get a JSON-serializable summary of the whole report.

        :return: dictionary with type, title, timestamp, summary
            and rows
        """
        return {
            "report_type": self._report_type.value,
            "title": self._title,
            "generated_at": self._generated_at.isoformat(),
            "summary": self._summary,
            "rows": self._rows,
        }

    def to_text(self) -> str:
        """
        Render the report as human-readable plain text.

        :return: formatted text report
        """
        lines = [
            self._title,
            f"Сформирован: {self._generated_at.isoformat(timespec='seconds')}",
            "",
            "Сводка:",
        ]
        for key, value in self._summary.items():
            lines.append(f"  {key}: {value}")
        lines.append("")
        lines.append(f"Данные ({len(self._rows)}):")
        for row in self._rows:
            fields = ", ".join(
                f"{name}={row[name]}" for name in self._fieldnames
            )
            lines.append(f"  {fields}")
        return "\n".join(lines)

    def __str__(self) -> str:
        """
        Build a short human-readable representation of the report.

        :return: string with type, title and row count
        """
        return (
            f"Report[{self._report_type.value}] {self._title} "
            f"({len(self._rows)} rows)"
        )
