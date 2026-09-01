"""Formal account password policy (HCT-512).

Login, registration and password rotation share one rule: 8–256 characters,
with at least one English letter and one digit. PIN remains six digits and is
out of scope.
"""

from __future__ import annotations

from collections.abc import Callable

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 256
PASSWORD_FORMAT_INVALID = "PASSWORD_FORMAT_INVALID"

# Teaching demo defaults. The legacy value has no digit and cannot be submitted
# after HCT-512; authenticate() may one-time upgrade a matching hash.
TEACHING_PASSWORD_DEFAULT = "DemoOnly-ChangeMe1!"
TEACHING_PASSWORD_LEGACY = "DemoOnly-ChangeMe!"
TEACHING_ACTOR_IDS = frozenset(
    {"demo-parent", "demo-child", "grandpa-demo", "grandma-demo"}
)


def password_meets_policy(password: str) -> bool:
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        return False
    has_letter = any("A" <= char <= "Z" or "a" <= char <= "z" for char in password)
    has_digit = any("0" <= char <= "9" for char in password)
    return has_letter and has_digit


def assert_password_policy(password: str) -> str:
    if not password_meets_policy(password):
        raise ValueError(PASSWORD_FORMAT_INVALID)
    return password


def teaching_password_hash_if_legacy_upgrade(
    actor_id: str,
    submitted: str,
    current_hash: str,
    *,
    verify: Callable[[str, str], bool],
    hash_password: Callable[[str], str],
) -> str | None:
    """Upgrade the old teaching password hash when the new default is submitted."""
    if actor_id not in TEACHING_ACTOR_IDS:
        return None
    if submitted != TEACHING_PASSWORD_DEFAULT:
        return None
    if not verify(TEACHING_PASSWORD_LEGACY, current_hash):
        return None
    return hash_password(submitted)
