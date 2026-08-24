from __future__ import annotations

import json
from pathlib import Path

import pytest

from hct402_predict_blind import load_blind_inputs


def test_blind_loader_rejects_assistant_targets(tmp_path: Path) -> None:
    path = tmp_path / "inputs.jsonl"
    path.write_text(
        json.dumps(
            {
                "sample_id": "blind-1",
                "messages": [
                    {"role": "user", "content": "question"},
                    {"role": "assistant", "content": "target"},
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="BLIND_INPUT_CONTAINS_TARGET"):
        load_blind_inputs(path)


def test_blind_loader_accepts_prompt_only_records(tmp_path: Path) -> None:
    path = tmp_path / "inputs.jsonl"
    path.write_text(
        json.dumps(
            {
                "sample_id": "blind-1",
                "messages": [{"role": "user", "content": "question"}],
            }
        ),
        encoding="utf-8",
    )
    assert load_blind_inputs(path)[0]["sample_id"] == "blind-1"
