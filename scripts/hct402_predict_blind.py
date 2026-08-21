"""Generate real-model predictions for the HCT-402 blind input split.

This command is deliberately separate from the evaluator: it loads only blind
inputs, never labels, and writes predictions to an external experiment
directory.  Use ``hct402_evaluate_blind.py`` afterwards with the held-out
labels in a controlled evaluation step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def load_blind_inputs(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict) or not isinstance(value.get("sample_id"), str):
            raise ValueError(f"INVALID_BLIND_INPUT:{line_number}")
        messages = value.get("messages")
        if not isinstance(messages, list) or any(
            isinstance(message, dict) and message.get("role") == "assistant"
            for message in messages
        ):
            raise ValueError(f"BLIND_INPUT_CONTAINS_TARGET:{line_number}")
        records.append(value)
    if not records:
        raise ValueError("BLIND_INPUT_EMPTY")
    ids = [record["sample_id"] for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("BLIND_INPUT_DUPLICATE_ID")
    return records


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").removeprefix("json").strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def generate_predictions(
    inputs: list[dict[str, Any]],
    *,
    base_model: str,
    adapter: Path | None,
    max_new_tokens: int,
) -> list[dict[str, Any]]:
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError(
            "PREDICTION_DEPENDENCIES_MISSING: install torch and transformers "
            "in the controlled evaluation environment"
        ) from exc

    tokenizer = AutoTokenizer.from_pretrained(base_model, use_fast=True)
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        device_map="auto" if torch.cuda.is_available() else None,
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else None,
    )
    if adapter is not None:
        try:
            from peft import PeftModel
        except ImportError as exc:
            raise RuntimeError("PREDICTION_DEPENDENCIES_MISSING: install peft") from exc
        model = PeftModel.from_pretrained(model, str(adapter))
    model.eval()
    predictions: list[dict[str, Any]] = []
    for record in inputs:
        messages = record["messages"]
        if not hasattr(tokenizer, "apply_chat_template"):
            raise RuntimeError("TOKENIZER_CHAT_TEMPLATE_REQUIRED")
        encoded = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
        )
        if hasattr(encoded, "to"):
            encoded = encoded.to(model.device)
        with torch.no_grad():
            generated = model.generate(encoded, max_new_tokens=max_new_tokens, do_sample=False)
        new_tokens = generated[0][encoded.shape[-1] :]
        decoded = tokenizer.decode(new_tokens, skip_special_tokens=True)
        output = _extract_json_object(decoded)
        predictions.append({"sample_id": record["sample_id"], "output": output or {}})
    return predictions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        inputs = load_blind_inputs(args.inputs)
        if args.max_new_tokens < 1 or args.max_new_tokens > 4096:
            raise ValueError("MAX_NEW_TOKENS_INVALID")
        predictions = (
            [{"sample_id": record["sample_id"], "output": {}} for record in inputs]
            if args.dry_run
            else generate_predictions(
                inputs,
                base_model=args.base_model,
                adapter=args.adapter,
                max_new_tokens=args.max_new_tokens,
            )
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "\n".join(
                json.dumps(prediction, ensure_ascii=False, separators=(",", ":"))
                for prediction in predictions
            )
            + "\n",
            encoding="utf-8",
        )
        metadata = {
            "schema_version": "hct402-blind-prediction/v1",
            "status": "DRY_RUN_VALIDATED" if args.dry_run else "COMPLETED",
            "model_name": args.base_model,
            "model_version": args.model_version,
            "adapter_external_path": args.adapter is not None,
            "input_sha256": sha256_file(args.inputs),
            "prediction_count": len(predictions),
            "raw_generation_text_recorded": False,
            "labels_loaded": False,
            "output_external_to_git": True,
        }
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
