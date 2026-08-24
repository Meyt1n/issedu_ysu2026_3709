"""Request-scoped context used to connect authorization decisions to a request."""

from __future__ import annotations

from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(value: str) -> Token[str | None]:
    """Set the current request ID and return a token for restoring the prior value."""
    return _request_id.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous request context after an ASGI request completes."""
    _request_id.reset(token)


def current_request_id() -> str | None:
    return _request_id.get()
