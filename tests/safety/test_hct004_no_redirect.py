"""
Tests for HCT-004 no-redirect keyword scanner.
"""

import tempfile
from pathlib import Path

from scripts.scan_no_redirect import PROHIBITED, scan_file


class TestScanFile:
    def test_clean_file_no_violations(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ts", delete=False, encoding="utf-8"
        ) as f:
            f.write("const apiUrl = '/api/v1/weather';\n")
            f.write("export function getWeather() {}\n")
            path = Path(f.name)

        violations = scan_file(path)
        path.unlink()
        assert violations == []

    def test_buy_medicine_violation(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".vue", delete=False, encoding="utf-8"
        ) as f:
            f.write("<template>\n  <a href='/buy_medicine'>Purchase</a>\n</template>\n")
            path = Path(f.name)

        violations = scan_file(path)
        path.unlink()
        assert len(violations) > 0
        assert any("drug_purchase" in v for v in violations)

    def test_teleconsultation_violation(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Redirect to online_consult service\n")
            f.write("def consult(): pass\n")
            path = Path(f.name)

        violations = scan_file(path)
        path.unlink()
        assert len(violations) > 0

    def test_ad_redirect_violation(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ts", delete=False, encoding="utf-8"
        ) as f:
            f.write("const adRedirectUrl = 'https://example.com';\n")
            path = Path(f.name)

        violations = scan_file(path)
        path.unlink()
        assert len(violations) > 0
        assert any("ad_redirect" in v for v in violations)

    def test_chinese_violation(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# 在线购药功能说明\n")
            path = Path(f.name)

        violations = scan_file(path)
        path.unlink()
        assert len(violations) > 0
        assert any("在线购药" in v for v in violations)


class TestProhibitedKeywords:
    def test_all_categories_present(self):
        """Ensure all required categories are covered."""
        assert "drug_purchase" in PROHIBITED
        assert "teleconsultation" in PROHIBITED
        assert "ad_redirect" in PROHIBITED
        assert "commission" in PROHIBITED
        assert "pharmacy" in PROHIBITED

    def test_no_empty_lists(self):
        for category, keywords in PROHIBITED.items():
            assert len(keywords) > 0, f"Category '{category}' has no keywords"
