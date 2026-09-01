from app.auth import hash_password, verify_password
from app.password_policy import (
    PASSWORD_FORMAT_INVALID,
    TEACHING_PASSWORD_DEFAULT,
    TEACHING_PASSWORD_LEGACY,
    assert_password_policy,
    password_meets_policy,
    teaching_password_hash_if_legacy_upgrade,
)


def test_password_policy_accepts_mixed_english_and_digits() -> None:
    assert password_meets_policy("password-123")
    assert password_meets_policy(TEACHING_PASSWORD_DEFAULT)
    assert assert_password_policy("Ab345678") == "Ab345678"


def test_password_policy_rejects_short_letter_only_or_digit_only() -> None:
    for candidate in ("pass1", "password", "12345678", TEACHING_PASSWORD_LEGACY, "密码12345678"):
        assert password_meets_policy(candidate) is False
        try:
            assert_password_policy(candidate)
        except ValueError as exc:
            assert str(exc) == PASSWORD_FORMAT_INVALID
        else:
            raise AssertionError(candidate)


def test_legacy_teaching_password_upgrades_only_for_known_demo_actors() -> None:
    legacy_hash = hash_password(TEACHING_PASSWORD_LEGACY)
    upgraded = teaching_password_hash_if_legacy_upgrade(
        "demo-parent",
        TEACHING_PASSWORD_DEFAULT,
        legacy_hash,
        verify=verify_password,
        hash_password=hash_password,
    )
    assert upgraded is not None
    assert verify_password(TEACHING_PASSWORD_DEFAULT, upgraded)
    assert teaching_password_hash_if_legacy_upgrade(
        "stranger",
        TEACHING_PASSWORD_DEFAULT,
        legacy_hash,
        verify=verify_password,
        hash_password=hash_password,
    ) is None
