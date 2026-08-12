"""
Log masking — prevent secrets and health data from appearing in logs.

This module provides a logging Filter that redacts sensitive patterns
before log records are emitted to any handler.
"""

from __future__ import annotations

import logging
import re

# ── Secret patterns ──────────────────────────────────────────────
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "api_key",
        re.compile(r"[A-Za-z0-9_\-]{20,}(?:key|token|secret|password)[A-Za-z0-9_\-]*", re.I),
    ),
    ("bearer_token", re.compile(r"bearer\s+[A-Za-z0-9_\-\.]+", re.I)),
    ("basic_auth", re.compile(r"basic\s+[A-Za-z0-9+/=]+", re.I)),
    ("password_in_json", re.compile(r'"password"\s*[:=]\s*"[^"]*"', re.I)),
    ("password_equals", re.compile(r'password\s*=\s*"[^"]*"', re.I)),
    ("token_in_json", re.compile(r'"(?:access_)?token"\s*:\s*"[^"]*"', re.I)),
    ("secret_in_json", re.compile(r'"(?:secret|api_key|private_key)"\s*:\s*"[^"]*"', re.I)),
    ("connection_string", re.compile(r"://[^:@]+:[^@]+@", re.I)),
]

# ── Health field patterns ────────────────────────────────────────
_HEALTH_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "health_kv",
        re.compile(
            r'"(?:disease|drug_name|drug|allergy|symptom|diagnosis|'
            r'report|prescription|medication|dosage|blood_pressure|heart_rate)"'
            r'\s*:\s*"[^"]{2,}"',
            re.I,
        ),
    ),
    (
        "health_payload_block",
        re.compile(
            r'"(?:payload|evidence|state)"\s*:\s*\{[^}]{0,200}\}',
            re.I,
        ),
    ),
    (
        "display_name_value",
        re.compile(r'"display_name"\s*:\s*"([^"]{2,})"', re.I),
    ),
    (
        "ocr_text_value",
        re.compile(r'"ocr_text"\s*:\s*"([^"]{0,200})"', re.I),
    ),
]

REDACTED = "<REDACTED>"


def mask_secrets(text: str) -> str:
    """Replace secret patterns in *text* with REDACTED."""
    for _name, pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def mask_health_fields(text: str) -> str:
    """Replace health-related field values in *text* with REDACTED."""
    for _name, pattern in _HEALTH_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def mask_all(text: str) -> str:
    """Apply all masking rules and return the sanitised string."""
    return mask_health_fields(mask_secrets(text))


class LogMaskingFilter(logging.Filter):
    """logging.Filter that redacts secrets and health data from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, "msg") and isinstance(record.msg, str):
            record.msg = mask_all(record.msg)
        if record.args and isinstance(record.args, (tuple, list)):
            record.args = tuple(
                mask_all(str(a)) if isinstance(a, str) else a for a in record.args
            )
        elif record.args and isinstance(record.args, dict):
            record.args = {
                k: mask_all(str(v)) if isinstance(v, str) else v
                for k, v in record.args.items()
            }
        return True


def install_log_mask() -> None:
    """Attach the LogMaskingFilter to the root logger (once)."""
    root = logging.getLogger()
    if not any(isinstance(f, LogMaskingFilter) for f in root.filters):
        root.addFilter(LogMaskingFilter())
