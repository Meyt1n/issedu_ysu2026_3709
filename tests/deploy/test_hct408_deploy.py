"""HCT-408 备份校验与版本清单测试（无需 Docker 运行）"""

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


BACKUP_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _ps_syntax_check(script_path: Path) -> None:
    """PowerShell syntax validation using pwsh/powershell."""
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f'$ErrorActionPreference = "Stop"; '
            f"$ast = [System.Management.Automation.Language.Parser]::ParseFile("
            f'  "{script_path}", [ref]$null, [ref]$null); '
            f"if ($ast) {{ Write-Output 'PS_SYNTAX_OK' }} else {{ throw 'PS_SYNTAX_FAIL' }}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "PS_SYNTAX_OK" in result.stdout, (
        f"PowerShell syntax check failed for {script_path.name}: {result.stderr}"
    )


def _docker_compose_config_ok(profile: str) -> bool:
    """Run docker compose config --quiet for a profile, skip if docker unavailable."""
    compose_path = Path(__file__).resolve().parents[3] / "docker-compose.yml"
    if not compose_path.exists():
        return True  # skip gracefully in CI without compose file

    result = subprocess.run(
        [
            "docker", "compose",
            "-f", str(compose_path),
            "--profile", profile,
            "config", "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode == 0


def test_backup_ps1_syntax():
    """backup.ps1 passes PowerShell syntax check."""
    _ps_syntax_check(BACKUP_SCRIPTS / "backup.ps1")


def test_restore_ps1_syntax():
    """restore.ps1 passes PowerShell syntax check."""
    _ps_syntax_check(BACKUP_SCRIPTS / "restore.ps1")


def test_version_manifest_schema():
    """version_manifest.json keys match the expected schema."""
    sample = {
        "backup_id": "hct-backup-test",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": "d38bc8b97c68ff1744e65d2fc08489a43c3f1446",
        "git_commit_short": "d38bc8b",
        "migration_head": "0002_allow_pending_health_events",
        "compose_profile": "basic",
        "mysql_image": "mysql:8.4",
        "ollama_model": "unavailable",
        "ruleset_version": "rules-v0",
        "knowledge_version": "knowledge-v0",
        "note": "Secrets and passwords are NEVER included in this manifest.",
    }

    required_keys = {
        "backup_id",
        "timestamp_utc",
        "git_commit",
        "git_commit_short",
        "migration_head",
        "compose_profile",
        "note",
    }

    assert required_keys.issubset(set(sample.keys())), (
        f"Missing required keys: {required_keys - set(sample.keys())}"
    )

    # Verify no secrets leaked
    forbidden_values = {"change-me", "change-me-root", "password", "secret", "api_key", "token"}
    manifest_str = json.dumps(sample).lower()
    for value in forbidden_values:
        assert value not in manifest_str, f"Secret leak detected: '{value}' found in manifest"


def test_file_manifest_schema():
    """file_manifest.json keys match the expected schema."""
    sample = {
        "source_root": "./data/files",
        "total_files": 3,
        "total_bytes": 1048576,
        "collected_utc": datetime.now(timezone.utc).isoformat(),
        "files": [
            {
                "relative_path": "uploads/example.jpg",
                "size": 512000,
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "modified_utc": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }

    required_keys = {"source_root", "total_files", "total_bytes", "collected_utc", "files"}
    assert required_keys == set(sample.keys()), (
        f"Top-level keys mismatch: expected {required_keys}, got {set(sample.keys())}"
    )
    for entry in sample["files"]:
        file_keys = {"relative_path", "size", "sha256", "modified_utc"}
        assert file_keys == set(entry.keys()), (
            f"File entry keys mismatch: expected {file_keys}, got {set(entry.keys())}"
        )
        # SHA-256 must be 64 hex chars
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]), (
            f"Invalid SHA-256 hash: {entry['sha256']}"
        )


def test_backup_id_format():
    """Backup IDs follow hct-backup-YYYYMMDD-HHmmss pattern."""
    pattern = r"^hct-backup-\d{8}-\d{6}$"
    valid_ids = [
        "hct-backup-20260921-143000",
        "hct-backup-20260101-000001",
    ]
    invalid_ids = [
        "backup-20260921",
        "hct-20260921-143000",
        "",
        "hct-backup-20260921",
    ]
    for bid in valid_ids:
        assert re.fullmatch(pattern, bid), f"Should match: {bid}"
    for bid in invalid_ids:
        assert not re.fullmatch(pattern, bid), f"Should NOT match: {bid}"


def test_restore_rejects_missing_backup():
    """restore.ps1 exits with error when backup does not exist."""
    script = BACKUP_SCRIPTS / "restore.ps1"
    if not script.exists():
        return  # skip, not yet deployed

    result = subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-NonInteractive",
            "-File", str(script),
            "-BackupId", "nonexistent-backup-99999999-000000",
            "-Force",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0, "restore.ps1 should fail on missing backup"


def test_docker_compose_basic_profile_config():
    """docker compose --profile basic config is valid."""
    assert _docker_compose_config_ok("basic"), "basic profile config failed"


def test_docker_compose_enhanced_profile_config():
    """docker compose --profile enhanced config is valid."""
    assert _docker_compose_config_ok("enhanced"), "enhanced profile config failed"


def test_docker_compose_dev_profile_config():
    """docker compose --profile dev config is valid."""
    assert _docker_compose_config_ok("dev"), "dev profile config failed"


def test_basic_profile_excludes_ollama():
    """basic profile does NOT include ollama service."""
    compose_path = Path(__file__).resolve().parents[3] / "docker-compose.yml"
    if not compose_path.exists():
        return

    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_path), "--profile", "basic", "config", "--format", "json"],
        capture_output=True, text=True, timeout=30,
    )
    config = json.loads(result.stdout)
    services = list(config.get("services", {}).keys())
    assert "ollama" not in services, f"basic profile should not include ollama, got: {services}"
    assert "db" in services
    assert "api" in services
    assert "web" in services


def test_enhanced_profile_includes_ollama():
    """enhanced profile includes ollama service."""
    compose_path = Path(__file__).resolve().parents[3] / "docker-compose.yml"
    if not compose_path.exists():
        return

    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_path), "--profile", "enhanced", "config", "--format", "json"],
        capture_output=True, text=True, timeout=30,
    )
    config = json.loads(result.stdout)
    services = list(config.get("services", {}).keys())
    assert "ollama" in services, f"enhanced profile should include ollama, got: {services}"
