"""Unit tests for HCT-208 hard_sample module — pure logic, no database."""

import pytest

from app.hard_sample import (
    VALID_CATEGORIES,
    _canonical_hash,
    _validate_category,
)


class TestCategoryValidation:
    def test_valid_categories_accepted(self):
        for cat in VALID_CATEGORIES:
            _validate_category(cat)  # should not raise

    def test_invalid_category_rejected(self):
        with pytest.raises(ValueError, match="INVALID_CATEGORY"):
            _validate_category("invalid_category")

    def test_empty_string_rejected(self):
        with pytest.raises(ValueError, match="INVALID_CATEGORY"):
            _validate_category("")


class TestCanonicalHash:
    def test_deterministic_same_input(self):
        h1 = _canonical_hash(sample_ids=["a", "b"], event_ids=["e1", "e2"], version="v1")
        h2 = _canonical_hash(sample_ids=["a", "b"], event_ids=["e1", "e2"], version="v1")
        assert h1 == h2
        assert len(h1) == 64  # SHA-256

    def test_order_independent_sample_ids(self):
        h1 = _canonical_hash(sample_ids=["b", "a", "c"], event_ids=["e1"], version="v1")
        h2 = _canonical_hash(sample_ids=["a", "c", "b"], event_ids=["e1"], version="v1")
        assert h1 == h2

    def test_order_independent_event_ids(self):
        h1 = _canonical_hash(sample_ids=["a"], event_ids=["e3", "e1", "e2"], version="v1")
        h2 = _canonical_hash(sample_ids=["a"], event_ids=["e1", "e2", "e3"], version="v1")
        assert h1 == h2

    def test_different_version_different_hash(self):
        h1 = _canonical_hash(sample_ids=["a"], event_ids=["e1"], version="v1")
        h2 = _canonical_hash(sample_ids=["a"], event_ids=["e1"], version="v2")
        assert h1 != h2

    def test_different_samples_different_hash(self):
        h1 = _canonical_hash(sample_ids=["a"], event_ids=["e1"], version="v1")
        h2 = _canonical_hash(sample_ids=["b"], event_ids=["e1"], version="v1")
        assert h1 != h2

    def test_hash_is_hex_string(self):
        h = _canonical_hash(sample_ids=["a"], event_ids=["e1"], version="v1")
        int(h, 16)  # should parse as hex


class TestConstants:
    def test_five_categories(self):
        assert VALID_CATEGORIES == {
            "hard_font",
            "hard_layout",
            "hard_condition",
            "hard_similar",
            "hard_foreign",
        }
