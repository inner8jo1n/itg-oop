from datetime import datetime

import pytest

from bank.enums import ReportType
from bank.exceptions import InvalidOperationError
from bank.reports.report import Report

DAY_TIME = datetime(2024, 1, 1, 12, 0, 0)


def make_report(**overrides) -> Report:
    kwargs = {
        "report_type": ReportType.CLIENT,
        "title": "Test Report",
        "generated_at": DAY_TIME,
        "summary": {"key": "value"},
        "fieldnames": ["a", "b"],
        "rows": [{"a": "1", "b": "2"}],
    }
    kwargs.update(overrides)
    return Report(**kwargs)


class TestReportCreation:
    def test_creates_report_with_expected_fields(self):
        report = make_report()
        assert report.report_type == ReportType.CLIENT
        assert report.title == "Test Report"
        assert report.generated_at == DAY_TIME
        assert report.summary == {"key": "value"}
        assert report.fieldnames == ["a", "b"]
        assert report.rows == [{"a": "1", "b": "2"}]

    def test_accepts_empty_rows(self):
        report = make_report(rows=[])
        assert report.rows == []

    def test_rejects_invalid_report_type(self):
        with pytest.raises(InvalidOperationError):
            make_report(report_type="client")

    def test_rejects_empty_title(self):
        with pytest.raises(InvalidOperationError):
            make_report(title="   ")

    def test_rejects_empty_fieldnames(self):
        with pytest.raises(InvalidOperationError):
            make_report(fieldnames=[])

    def test_rejects_row_with_mismatched_keys(self):
        with pytest.raises(InvalidOperationError):
            make_report(fieldnames=["a", "b"], rows=[{"a": "1", "c": "3"}])

    def test_rejects_row_missing_a_field(self):
        with pytest.raises(InvalidOperationError):
            make_report(fieldnames=["a", "b"], rows=[{"a": "1"}])

    def test_summary_is_copied_not_aliased(self):
        source = {"key": "value"}
        report = make_report(summary=source)
        source["key"] = "mutated"
        assert report.summary == {"key": "value"}

    def test_rows_is_copied_not_aliased(self):
        source = [{"a": "1", "b": "2"}]
        report = make_report(rows=source)
        source[0]["a"] = "mutated"
        assert report.rows == [{"a": "1", "b": "2"}]

    def test_rows_property_returns_a_copy(self):
        report = make_report()
        report.rows[0]["a"] = "mutated"
        assert report.rows == [{"a": "1", "b": "2"}]


class TestReportToDict:
    def test_to_dict_contains_expected_fields(self):
        report = make_report()
        data = report.to_dict()
        assert data["report_type"] == "client"
        assert data["title"] == "Test Report"
        assert data["generated_at"] == DAY_TIME.isoformat()
        assert data["summary"] == {"key": "value"}
        assert data["rows"] == [{"a": "1", "b": "2"}]


class TestReportToText:
    def test_to_text_includes_title_and_summary(self):
        report = make_report()
        text = report.to_text()
        assert "Test Report" in text
        assert "key: value" in text

    def test_to_text_includes_row_data(self):
        report = make_report()
        text = report.to_text()
        assert "a=1" in text
        assert "b=2" in text

    def test_to_text_handles_empty_rows(self):
        report = make_report(rows=[])
        text = report.to_text()
        assert "Данные (0)" in text


class TestReportString:
    def test_str_includes_type_title_and_row_count(self):
        report = make_report()
        text = str(report)
        assert "client" in text
        assert "Test Report" in text
        assert "1 rows" in text
