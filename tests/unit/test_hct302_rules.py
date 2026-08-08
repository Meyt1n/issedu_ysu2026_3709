"""HCT-302: Rules engine unit tests."""

from datetime import UTC, datetime, timedelta

from app.rules import (
    allergy_conflict,
    duplicate_ingredient,
    expiry_check,
    low_stock,
    run_rules,
)


def test_expiry_past():
    expiry = (datetime.now(UTC) - timedelta(days=10)).date().isoformat()
    facts = {"drugs": [{"name": "old-drug", "expiry_date": expiry, "added_by": "e1"}]}
    alerts = expiry_check(facts)
    assert len(alerts) == 1
    assert alerts[0].level == "SEVERE"

def test_expiry_soon():
    expiry = (datetime.now(UTC) + timedelta(days=20)).date().isoformat()
    facts = {"drugs": [{"name": "soon-drug", "expiry_date": expiry, "added_by": "e1"}]}
    alerts = expiry_check(facts)
    assert len(alerts) == 1
    assert alerts[0].level == "WARNING"

def test_expiry_fine():
    expiry = (datetime.now(UTC) + timedelta(days=100)).date().isoformat()
    facts = {"drugs": [{"name": "fine-drug", "expiry_date": expiry, "added_by": "e1"}]}
    assert expiry_check(facts) == []

def test_low_stock():
    facts = {"drugs": [{"name": "rare", "stock": 2, "added_by": "e1"}]}
    alerts = low_stock(facts)
    assert len(alerts) == 1

def test_ok_stock():
    facts = {"drugs": [{"name": "plenty", "stock": 100, "added_by": "e1"}]}
    assert low_stock(facts) == []

def test_duplicate_ingredient():
    facts = {"drugs": [
        {"name": "a", "ingredient": "ibuprofen", "added_by": "e1"},
        {"name": "b", "ingredient": "ibuprofen", "added_by": "e2"},
    ]}
    alerts = duplicate_ingredient(facts)
    assert len(alerts) == 1
    assert len(alerts[0].source_event_ids) == 2

def test_allergy_conflict():
    facts = {
        "allergies": [{"name": "penicillin"}],
        "drugs": [{"name": "penicillin V", "added_by": "e1"}],
    }
    alerts = allergy_conflict(facts)
    assert len(alerts) == 1
    assert alerts[0].level == "SEVERE"

def test_no_allergy_conflict():
    facts = {
        "allergies": [{"name": "penicillin"}],
        "drugs": [{"name": "aspirin", "ingredient": "asa", "added_by": "e1"}],
    }
    assert allergy_conflict(facts) == []

def test_full_engine():
    facts = {
        "drugs": [
            {"name": "aspirin", "stock": 3, "added_by": "e1"},
        ],
        "allergies": [],
    }
    alerts = run_rules(facts)
    assert len(alerts) >= 1  # low_stock
