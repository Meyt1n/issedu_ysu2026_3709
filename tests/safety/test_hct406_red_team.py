"""HCT-406: Red-team tests for health assistant safety boundaries."""

import pytest

from app.red_team import (
    RED_TEAM_CASES,
    ExpectedBehavior,
    RiskCategory,
    get_case_by_id,
    get_red_team_cases,
)


# ── Case registry ────────────────────────────────────────────────────

class TestRedTeamRegistry:
    def test_all_categories_covered(self):
        categories = {c.category for c in RED_TEAM_CASES}
        assert RiskCategory.MEDICAL_BOUNDARY in categories
        assert RiskCategory.CROSS_AUTH in categories
        assert RiskCategory.PROMPT_INJECTION in categories
        assert RiskCategory.REFERRAL in categories
        assert RiskCategory.DATA_EXFIL in categories

    def test_minimum_cases_per_category(self):
        counts: dict[RiskCategory, int] = {}
        for c in RED_TEAM_CASES:
            counts[c.category] = counts.get(c.category, 0) + 1
        for cat, count in counts.items():
            assert count >= 3, f"{cat} has only {count} cases (need ≥3)"

    def test_all_cases_have_expected_behavior(self):
        for c in RED_TEAM_CASES:
            assert c.expected, f"Case {c.id} missing expected behavior"

    def test_filter_by_category(self):
        medical = get_red_team_cases(RiskCategory.MEDICAL_BOUNDARY)
        assert all(c.category == RiskCategory.MEDICAL_BOUNDARY for c in medical)
        assert len(medical) >= 3

    def test_get_case_by_id(self):
        case = get_case_by_id("MED-001")
        assert case is not None
        assert case.category == RiskCategory.MEDICAL_BOUNDARY

    def test_get_missing_case(self):
        assert get_case_by_id("ZZZ-999") is None

    def test_all_ids_unique(self):
        ids = [c.id for c in RED_TEAM_CASES]
        assert len(ids) == len(set(ids))

    def test_total_case_count(self):
        assert len(RED_TEAM_CASES) >= 12, f"Only {len(RED_TEAM_CASES)} cases"


# ── Case definitions (stub runner — real execution is integration test) ──

class TestRedTeamDefinitions:
    """Verify each case has required fields and sensible payloads."""

    def test_medical_cases_have_diagnosis_or_prescription_or_dosage(self):
        keywords = ["诊断", "处方", "剂量", "停药", "换药", "开药", "diagnos", "prescript"]
        for c in get_red_team_cases(RiskCategory.MEDICAL_BOUNDARY):
            text = (c.name + c.description + str(c.payload)).lower()
            assert any(kw in text for kw in keywords), \
                f"{c.id} ({c.name}) should target medical decision-making"

    def test_prompt_injection_cases_mention_override_or_ignore(self):
        inj_keywords = ["忽略", "override", "ignore", "system", "prompt", "管理员", "admin"]
        for c in get_red_team_cases(RiskCategory.PROMPT_INJECTION):
            text = (c.name + c.description + str(c.payload)).lower()
            assert any(kw in text for kw in inj_keywords), \
                f"{c.id} ({c.name}) should mention injection vectors"

    def test_referral_cases_have_external_requests(self):
        ref_keywords = ["购买", "链接", "问诊", "推荐", "buy", "link", "purchase"]
        for c in get_red_team_cases(RiskCategory.REFERRAL):
            text = (c.name + c.description + str(c.payload)).lower()
            assert any(kw in text for kw in ref_keywords), \
                f"{c.id} ({c.name}) should involve referral/advertising"

    def test_exfil_cases_have_dump_export(self):
        exf_keywords = ["导出", "导出", "dump", "export", "csv", "全部", "所有"]
        for c in get_red_team_cases(RiskCategory.DATA_EXFIL):
            text = (c.name + c.description + str(c.payload)).lower()
            assert any(kw in text for kw in exf_keywords), \
                f"{c.id} ({c.name}) should involve data exfiltration"

    def test_cross_auth_cases_have_other_household_or_member(self):
        for c in get_red_team_cases(RiskCategory.CROSS_AUTH):
            text = (c.name + c.description + str(c.payload)).lower()
            assert any(kw in text for kw in ["other", "跨", "全部成员", "所有家庭"]), \
                f"{c.id} ({c.name}) should target cross-authorization"

    def test_expected_refuse_has_escalation_for_medical(self):
        """Medical boundary violations should escalate to human."""
        for c in get_red_team_cases(RiskCategory.MEDICAL_BOUNDARY):
            assert c.expected in (
                ExpectedBehavior.REFUSE,
                ExpectedBehavior.REFUSE_WITH_ESCALATION,
                ExpectedBehavior.REFUSE_NO_EVIDENCE,
            ), f"{c.id} medical case should refuse"


# ── Stub: mark cases as tested when integration runner confirms safety ──

class TestRedTeamExecution:
    """Integration tests — run against live assistant when available.

    These tests are stubs: they define what the integration runner must check.
    Replace with actual FastAPI TestClient calls when the assistant endpoint
    is wired to a DB session.
    """

    ALL_CASES = RED_TEAM_CASES

    @pytest.mark.parametrize("case", [c.to_dict() for c in RED_TEAM_CASES])
    def test_red_team_case(self, case, client):
        """Placeholder — real execution requires TestClient fixture from conftest."""
        pytest.skip("Run via integration test runner with live assistant")
