"""Tests for JSON-safe conversion of SQL query row values."""
import json
from decimal import Decimal

from services.dataquery_service import _json_safe_value


def test_json_safe_value_converts_decimal():
    assert _json_safe_value(Decimal("10")) == 10
    assert _json_safe_value(Decimal("123.45")) == 123.45


def test_json_safe_value_nested_rows_are_json_serializable():
    rows = [{"amount": Decimal("99.99"), "count": Decimal("3")}]
    safe = [{k: _json_safe_value(v) for k, v in row.items()} for row in rows]
    dumped = json.dumps({"success": True, "rows": safe}, ensure_ascii=False)
    assert "99.99" in dumped
    assert "Decimal" not in dumped
