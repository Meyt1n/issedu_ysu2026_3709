"""HCT-431: request context is isolated and restorable."""

from app.request_context import current_request_id, reset_request_id, set_request_id


def test_request_context_restores_previous_value() -> None:
    assert current_request_id() is None
    outer = set_request_id("outer")
    inner = set_request_id("inner")
    assert current_request_id() == "inner"
    reset_request_id(inner)
    assert current_request_id() == "outer"
    reset_request_id(outer)
    assert current_request_id() is None
