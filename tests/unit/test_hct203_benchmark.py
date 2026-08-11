from __future__ import annotations

from pathlib import Path

import pytest

from hct203_benchmark import input_set_sha256, percentile_nearest_rank


def test_percentile_nearest_rank_is_deterministic() -> None:
    values = [5.0, 1.0, 4.0, 2.0, 3.0]

    assert percentile_nearest_rank(values, 0.50) == 3.0
    assert percentile_nearest_rank(values, 0.95) == 5.0


def test_percentile_rejects_empty_values() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        percentile_nearest_rank([], 0.95)


def test_input_set_hash_binds_filename_and_content(tmp_path: Path) -> None:
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    original = input_set_sha256([first, second])
    second.write_bytes(b"changed")

    assert input_set_sha256([first, second]) != original
