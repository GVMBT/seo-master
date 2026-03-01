"""Tests for smart Excel import in prices.py."""

from __future__ import annotations

from io import BytesIO

import openpyxl  # type: ignore[import-untyped]
import pytest

from routers.categories.prices import (
    _is_header_row,
    _is_numeric,
    parse_excel_rows,
)


# ---------------------------------------------------------------------------
# Helpers: create Excel bytes in memory
# ---------------------------------------------------------------------------


def _make_excel(rows: list[list[object]]) -> bytes:
    """Create minimal .xlsx bytes from a list of rows."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)  # type: ignore[union-attr]
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# 1. _is_numeric
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("89 900", True),
        ("89\xa0900", True),
        ("12345", True),
        ("12,5", True),
        ("12.5", True),
        ("0", True),
        ("abc", False),
        ("Название", False),
        ("", False),
        ("12-34", True),  # cleaned "1234" is numeric
    ],
)
def test_is_numeric(text: str, expected: bool) -> None:
    assert _is_numeric(text) == expected


# ---------------------------------------------------------------------------
# 2. _is_header_row
# ---------------------------------------------------------------------------


def test_header_detection_keyword() -> None:
    """Row containing a known keyword ('Цена') is detected as header."""
    assert _is_header_row(("Название", "Цена", "Описание")) is True


def test_header_detection_heuristic() -> None:
    """Row with all short text cells and no numbers is a header."""
    assert _is_header_row(("Товар", "Марка", "Тип")) is True


def test_numeric_row_not_header() -> None:
    """Row with numeric cells is NOT a header."""
    assert _is_header_row(("100", "200", "300")) is False


def test_empty_row_not_header() -> None:
    """Empty row is NOT a header."""
    assert _is_header_row((None, None, None)) is False


def test_mixed_row_with_keyword_is_header() -> None:
    """Row with keyword + other text is still a header."""
    assert _is_header_row(("Артикул", "Размер", "Ед. изм.")) is True


# ---------------------------------------------------------------------------
# 3. parse_excel_rows — with headers
# ---------------------------------------------------------------------------


def test_parse_with_headers() -> None:
    """Rows after header should be formatted as 'Header: Value | Header: Value'."""
    data = _make_excel([
        ["Название", "Цена", "Материал"],
        ["Стол", "15000", "Дерево"],
        ["Стул", "8000", "Металл"],
    ])
    result = parse_excel_rows(data)
    assert isinstance(result, list)
    assert len(result) == 2
    assert "Название: Стол" in result[0]
    assert "Цена: 15000" in result[0]
    assert "Материал: Дерево" in result[0]
    assert "|" in result[0]


def test_parse_without_headers() -> None:
    """When no headers detected, rows use em-dash separator."""
    data = _make_excel([
        ["12345", "89900", "500"],
        ["67890", "45000", "300"],
    ])
    result = parse_excel_rows(data)
    assert isinstance(result, list)
    assert len(result) == 2
    assert "\u2014" in result[0]


def test_single_row_not_header() -> None:
    """Single row file — treated as data, not header."""
    data = _make_excel([
        ["Название", "Цена"],
    ])
    result = parse_excel_rows(data)
    assert isinstance(result, list)
    assert len(result) == 1
    # Should be joined with em-dash (no header detection for single row)
    assert "\u2014" in result[0]


# ---------------------------------------------------------------------------
# 4. All columns read
# ---------------------------------------------------------------------------


def test_all_columns_read() -> None:
    """All 7 columns must appear in output."""
    data = _make_excel([
        ["Название", "Цена", "Артикул", "Бренд", "Размер", "Вес", "Категория"],
        ["Widget", "100", "W001", "BrandX", "M", "0.5", "Gadgets"],
    ])
    result = parse_excel_rows(data)
    assert isinstance(result, list)
    assert len(result) == 1
    line = result[0]
    assert "Widget" in line
    assert "W001" in line
    assert "BrandX" in line
    assert "Gadgets" in line
    assert "Размер: M" in line
    assert "Вес: 0.5" in line


def test_empty_columns_skipped() -> None:
    """None/empty cells should be skipped in output."""
    data = _make_excel([
        ["Название", "Цена", "Описание"],
        ["Стол", "15000", None],
    ])
    result = parse_excel_rows(data)
    assert isinstance(result, list)
    assert len(result) == 1
    # "Описание" header should not appear since value is None
    assert "Описание" not in result[0]
    assert "Название: Стол" in result[0]


# ---------------------------------------------------------------------------
# 5. Edge cases
# ---------------------------------------------------------------------------


def test_empty_file() -> None:
    """Empty worksheet returns 'empty'."""
    data = _make_excel([])
    result = parse_excel_rows(data)
    assert result == "empty"


def test_too_many_rows() -> None:
    """Over 1000 data rows returns 'too_many_rows'."""
    rows: list[list[object]] = [["Название", "Цена"]]
    for i in range(1002):
        rows.append([f"Item {i}", str(i * 100)])
    data = _make_excel(rows)
    result = parse_excel_rows(data)
    assert result == "too_many_rows"


def test_all_empty_rows_file() -> None:
    """File with only empty rows returns 'empty'."""
    data = _make_excel([
        [None, None],
        ["", ""],
    ])
    result = parse_excel_rows(data)
    assert result == "empty"


def test_header_with_extra_columns_beyond_header_count() -> None:
    """Data row with more columns than header gets 'Столбец N' labels."""
    data = _make_excel([
        ["Название", "Цена"],
        ["Стол", "15000", "Дополнительно"],
    ])
    result = parse_excel_rows(data)
    assert isinstance(result, list)
    assert len(result) == 1
    assert "Столбец 3: Дополнительно" in result[0]
