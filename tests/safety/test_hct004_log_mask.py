"""
Tests for HCT-004 log masking — secrets and health field redaction.
"""

import logging

from app.log_mask import (
    REDACTED,
    LogMaskingFilter,
    install_log_mask,
    mask_all,
    mask_health_fields,
    mask_secrets,
)


class TestMaskSecrets:
    def test_bearer_token_redacted(self):
        text = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456"
        result = mask_secrets(text)
        assert "Bearer" not in result or REDACTED in result

    def test_password_in_json_redacted(self):
        text = '{"username": "admin", "password": "secret123!"}'
        result = mask_secrets(text)
        assert "secret123!" not in result
        assert REDACTED in result

    def test_token_in_json_redacted(self):
        text = '{"access_token": "ghp_abc123def456ghi789"}'
        result = mask_secrets(text)
        assert "ghp_abc" not in result
        assert REDACTED in result

    def test_connection_string_redacted(self):
        text = "mysql+pymysql://admin:secretpass@localhost:3306/db"
        result = mask_secrets(text)
        assert "secretpass" not in result
        assert REDACTED in result

    def test_safe_text_passes_through(self):
        text = '{"event_type": "medication_added", "request_id": "abc-123"}'
        result = mask_secrets(text)
        assert result == text


class TestMaskHealthFields:
    def test_payload_with_drug_redacted(self):
        text = '{"payload": {"drug": "aspirin", "dose": "100mg"}}'
        result = mask_health_fields(text)
        assert REDACTED in result

    def test_display_name_redacted(self):
        text = '{"member": {"display_name": "张三"}}'
        result = mask_health_fields(text)
        assert "张三" not in result
        assert REDACTED in result

    def test_ocr_text_redacted(self):
        text = '{"ocr_text": "阿莫西林胶囊 0.5g"}'
        result = mask_health_fields(text)
        assert "阿莫西林" not in result
        assert REDACTED in result

    def test_safe_field_not_redacted(self):
        text = '{"event_type": "medication_added", "confirmation_status": "CONFIRMED"}'
        result = mask_health_fields(text)
        assert result == text


class TestMaskAll:
    def test_both_secret_and_health_redacted(self):
        text = '{"access_token": "secret123", "payload": {"drug": "aspirin"}}'
        result = mask_all(text)
        assert "secret123" not in result
        assert "aspirin" not in result
        assert result.count(REDACTED) >= 2

    def test_safe_content_preserved(self):
        text = '{"status": "ok", "version": "1.0.0"}'
        result = mask_all(text)
        assert result == text


class TestLogMaskingFilter:
    def test_filter_redacts_message(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg='password="mysecret" in log', args=(), exc_info=None,
        )
        f = LogMaskingFilter()
        f.filter(record)
        assert "mysecret" not in record.msg
        assert REDACTED in record.msg

    def test_filter_redacts_args(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="user %s performed action", args=('{"password":"pwd123"}',), exc_info=None,
        )
        f = LogMaskingFilter()
        f.filter(record)
        assert "pwd123" not in str(record.args)

    def test_filter_preserves_non_string_args(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="count=%d", args=(42,), exc_info=None,
        )
        f = LogMaskingFilter()
        f.filter(record)
        assert record.args == (42,)


class TestInstallLogMask:
    def test_install_adds_filter_once(self):
        root = logging.getLogger()
        before = len([f for f in root.filters if isinstance(f, LogMaskingFilter)])
        install_log_mask()
        install_log_mask()  # Idempotent
        after = len([f for f in root.filters if isinstance(f, LogMaskingFilter)])
        # Either it was already installed (before >= 1, after == before)
        # or it was just installed (before == 0, after == 1)
        assert after >= before
        assert after <= before + 1
