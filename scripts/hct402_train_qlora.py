"""Run a reproducible HCT-402 QLoRA experiment outside the repository.

The repository stores the launcher and audit logic only.  Prepared data,
checkpoints, adapters, caches and logs must be written to a controlled
external directory.  ``--dry-run`` validates a prepared dataset without
importing the heavyweight training stack; ``--run`` performs a real PEFT
training run with Transformers and bitsandbytes in the experiment environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REQUIRED_MANIFEST_FILES = ("train.jsonl", "validation.jsonl")
APPROVED_DATA_STATUSES = {
    "APPROVED_FOR_TRAINING",
    "RELEASED_FOR_TRAINING",
}


@dataclass(frozen=True)
class QLoRAConfig:
    base_model: str
    seed: int = 20260813
    epochs: float = 1.0
    learning_rate: float = 2e-5
    batch_size: int = 1
    gradient_accumulation_steps: int = 8
    max_seq_length: int = 4096
    warmup_ratio: float = 0.03
    lora_rank: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    target_modules: tuple[str, ...] = ("q_proj", "k_proj", "v_proj", "o_proj")
    use_4bit_nf4: bool = True
    assistant_only_loss: bool = True

    @property
    def effective_batch_size(self) -> int:
        return self.batch_size * self.gradient_accumulation_steps

    def validate(self) -> None:
        if not self.base_model.strip():
            raise ValueError("BASE_MODEL_REQUIRED")
        if self.seed < 0:
            raise ValueError("SEED_INVALID")
        if self.epochs <= 0 or self.learning_rate <= 0:
            raise ValueError("TRAINING_HYPERPARAMETER_INVALID")
        if self.batch_size < 1 or self.gradient_accumulation_steps < 1:
            raise ValueError("BATCH_CONFIGURATION_INVALID")
        if not 1 <= self.max_seq_length <= 32768:
            raise ValueError("MAX_SEQ_LENGTH_INVALID")
        if not 0 <= self.warmup_ratio < 1:
            raise ValueError("WARMUP_RATIO_INVALID")
        if self.lora_rank < 1 or self.lora_alpha < 1 or not 0 <= self.lora_dropout < 1:
            raise ValueError("LORA_CONFIGURATION_INVALID")
        if not self.target_modules:
            raise ValueError("LORA_TARGET_MODULES_REQUIRED")

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["target_modules"] = list(self.target_modules)
        result["effective_batch_size"] = self.effective_batch_size
        return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"INVALID_JSON:{path.name}:{line_number}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"INVALID_RECORD:{path.name}:{line_number}")
        records.append(record)
    return records


def load_and_validate_prepared_dataset(
    prepared_dir: Path,
    *,
    allow_synthetic_demo: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate the prepared split and return train/validation records.

    Blind inputs and labels are intentionally not loaded here.  A real run
    requires an approved manifest; the explicit demo flag is the only way to
    run the small synthetic fixture and its metadata remains marked as demo.
    """
    manifest_path = prepared_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("PREPARED_MANIFEST_REQUIRED")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("PREPARED_MANIFEST_INVALID")
    status = str(manifest.get("status") or "")
    is_synthetic = status == "PREPARED_SYNTHETIC_NOT_RELEASED" or manifest.get(
        "source_type"
    ) == "synthetic"
    if is_synthetic and not allow_synthetic_demo:
        raise ValueError("TRAINING_DATA_NOT_APPROVED:synthetic_fixture_only")
    if not is_synthetic and status not in APPROVED_DATA_STATUSES:
        raise ValueError(f"TRAINING_DATA_NOT_APPROVED:{status or 'missing_status'}")

    training_files = manifest.get("training_files")
    if not isinstance(training_files, dict):
        raise ValueError("TRAINING_FILES_MISSING")
    paths: dict[str, Path] = {}
    for split in REQUIRED_MANIFEST_FILES:
        relative = training_files.get(split.removesuffix(".jsonl"))
        if relative != split or Path(relative).is_absolute():
            raise ValueError(f"TRAINING_FILE_NOT_PINNED:{split}")
        path = prepared_dir / relative
        if not path.is_file():
            raise ValueError(f"TRAINING_FILE_MISSING:{split}")
        paths[split] = path

    train = load_jsonl(paths["train.jsonl"])
    validation = load_jsonl(paths["validation.jsonl"])
    for split, records in (("train", train), ("validation", validation)):
        if not records:
            raise ValueError(f"TRAINING_SPLIT_EMPTY:{split}")
        for record in records:
            messages = record.get("messages")
            if not isinstance(messages, list) or not messages:
                raise ValueError(f"MESSAGES_MISSING:{split}")
            assistant_count = sum(
                isinstance(message, dict) and message.get("role") == "assistant"
                for message in messages
            )
            if assistant_count != 1:
                raise ValueError(f"ASSISTANT_TARGET_INVALID:{split}")
    return manifest, train, validation


def assistant_only_projection(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the prompt/target boundary used by assistant-only loss."""
    assistant_indexes = [
        index for index, message in enumerate(messages) if message.get("role") == "assistant"
    ]
    if len(assistant_indexes) != 1:
        raise ValueError("ASSISTANT_TARGET_INVALID")
    index = assistant_indexes[0]
    target = messages[index].get("content")
    if not isinstance(target, str) or not target.strip():
        raise ValueError("ASSISTANT_TARGET_EMPTY")
    return {"prompt_messages": messages[:index], "target": target}


def build_run_metadata(
    prepared_dir: Path,
    manifest: dict[str, Any],
    config: QLoRAConfig,
    *,
    status: str,
) -> dict[str, Any]:
    config.validate()
    files = {
        relative: sha256_file(prepared_dir / relative)
        for relative in REQUIRED_MANIFEST_FILES
    }
    return {
        "schema_version": "hct402-qlora-run/v1",
        "status": status,
        "dataset_version": manifest.get("dataset_version"),
        "dataset_manifest_sha256": sha256_file(prepared_dir / "manifest.json"),
        "training_files_sha256": files,
        "evaluation_scope": (
            "synthetic_fixture_only"
            if manifest.get("status") == "PREPARED_SYNTHETIC_NOT_RELEASED"
            else "approved_external_dataset"
        ),
        "configuration": config.as_dict(),
        "secrets_and_raw_text": "not recorded",
        "artifacts_external_to_git": True,
    }


class AssistantOnlyCollator:
    """Pad tokenized examples while preserving ``-100`` label masking."""

    def __init__(self, tokenizer: Any) -> None:
        self.tokenizer = tokenizer

    def __call__(self, features: list[dict[str, list[int]]]) -> dict[str, Any]:
        import torch

        max_length = max(len(item["input_ids"]) for item in features)
        pad_id = self.tokenizer.pad_token_id
        if pad_id is None:
            pad_id = self.tokenizer.eos_token_id or 0
        input_ids = []
        attention_mask = []
        labels = []
        for item in features:
            padding = max_length - len(item["input_ids"])
            input_ids.append(item["input_ids"] + [pad_id] * padding)
            attention_mask.append(item["attention_mask"] + [0] * padding)
            labels.append(item["labels"] + [-100] * padding)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
        }


def _tokenize_assistant_example(
    tokenizer: Any,
    messages: list[dict[str, Any]],
    max_length: int,
) -> dict[str, list[int]]:
    projection = assistant_only_projection(messages)
    if not hasattr(tokenizer, "apply_chat_template"):
        raise RuntimeError("TOKENIZER_CHAT_TEMPLATE_REQUIRED")
    full_text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=False
    )
    prompt_text = tokenizer.apply_chat_template(
        projection["prompt_messages"], tokenize=False, add_generation_prompt=True
    )
    encoded = tokenizer(
        full_text,
        add_special_tokens=False,
        truncation=True,
        max_length=max_length,
    )
    input_ids = list(encoded["input_ids"])
    prompt_ids = list(tokenizer(prompt_text, add_special_tokens=False)["input_ids"])
    prompt_length = min(len(prompt_ids), len(input_ids))
    labels = [-100] * prompt_length + input_ids[prompt_length:]
    if not any(label != -100 for label in labels):
        raise ValueError("ASSISTANT_TARGET_TRUNCATED")
    return {
        "input_ids": input_ids,
        "attention_mask": [1] * len(input_ids),
        "labels": labels,
    }


def _import_training_stack() -> tuple[Any, Any, Any, Any, Any, Any, Any]:
    try:
        import torch
        from peft import LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            Trainer,
            TrainingArguments,
        )
    except ImportError as exc:
        raise RuntimeError(
            "TRAINING_DEPENDENCIES_MISSING: install torch, transformers, peft and "
            "bitsandbytes in the controlled training environment"
        ) from exc
    return (
        torch,
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        Trainer,
        TrainingArguments,
        (LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training),
    )


def train_qlora(
    prepared_dir: Path,
    output_dir: Path,
    config: QLoRAConfig,
    *,
    allow_synthetic_demo: bool = False,
) -> dict[str, Any]:
    manifest, train_records, validation_records = load_and_validate_prepared_dataset(
        prepared_dir,
        allow_synthetic_demo=allow_synthetic_demo,
    )
    config.validate()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("OUTPUT_DIR_MUST_BE_EMPTY")
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = build_run_metadata(
        prepared_dir,
        manifest,
        config,
        status="RUNNING",
    )
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    (
        torch,
        auto_model,
        auto_tokenizer,
        bits_config,
        trainer_class,
        training_args,
        peft_stack,
    ) = _import_training_stack()
    lora_config, _peft_model, get_peft_model, prepare_model_for_kbit_training = peft_stack
    random.seed(config.seed)
    torch.manual_seed(config.seed)
    compute_dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    quantization = bits_config(
        load_in_4bit=config.use_4bit_nf4,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=compute_dtype,
        bnb_4bit_use_double_quant=True,
    )
    model = auto_model.from_pretrained(
        config.base_model,
        quantization_config=quantization if config.use_4bit_nf4 else None,
        device_map="auto" if torch.cuda.is_available() else None,
        torch_dtype=compute_dtype if torch.cuda.is_available() else None,
    )
    tokenizer = auto_tokenizer.from_pretrained(config.base_model, use_fast=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    if config.use_4bit_nf4:
        model = prepare_model_for_kbit_training(model)
    model = get_peft_model(
        model,
        lora_config(
            r=config.lora_rank,
            lora_alpha=config.lora_alpha,
            lora_dropout=config.lora_dropout,
            target_modules=list(config.target_modules),
            bias="none",
            task_type="CAUSAL_LM",
        ),
    )
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()
    model.config.use_cache = False

    train_features = [
        _tokenize_assistant_example(tokenizer, record["messages"], config.max_seq_length)
        for record in train_records
    ]
    validation_features = [
        _tokenize_assistant_example(tokenizer, record["messages"], config.max_seq_length)
        for record in validation_records
    ]
    args = training_args(
        output_dir=str(output_dir / "checkpoints"),
        num_train_epochs=config.epochs,
        per_device_train_batch_size=config.batch_size,
        per_device_eval_batch_size=config.batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        learning_rate=config.learning_rate,
        warmup_ratio=config.warmup_ratio,
        logging_steps=10,
        evaluation_strategy="epoch",
        save_strategy="epoch",
        report_to=[],
        remove_unused_columns=False,
        fp16=bool(torch.cuda.is_available() and not torch.cuda.is_bf16_supported()),
        bf16=bool(torch.cuda.is_available() and torch.cuda.is_bf16_supported()),
        gradient_checkpointing=True,
        seed=config.seed,
    )
    trainer = trainer_class(
        model=model,
        args=args,
        train_dataset=train_features,
        eval_dataset=validation_features,
        data_collator=AssistantOnlyCollator(tokenizer),
    )
    trainer.train()
    trainer.save_model(str(output_dir / "adapter"))
    tokenizer.save_pretrained(str(output_dir / "adapter"))
    metadata["status"] = "COMPLETED"
    metadata["output"] = {"adapter_dir": "adapter", "checkpoints_dir": "checkpoints"}
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--base-model", default="Qwen/Qwen3-4B")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-synthetic-demo", action="store_true")
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--max-seq-length", type=int, default=4096)
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument("--lora-rank", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--target-modules", default="q_proj,k_proj,v_proj,o_proj")
    args = parser.parse_args()
    config = QLoRAConfig(
        base_model=args.base_model,
        seed=args.seed,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        max_seq_length=args.max_seq_length,
        lora_rank=args.lora_rank,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        target_modules=tuple(
            item.strip() for item in args.target_modules.split(",") if item.strip()
        ),
    )
    try:
        manifest, train, validation = load_and_validate_prepared_dataset(
            args.prepared_dir,
            allow_synthetic_demo=args.allow_synthetic_demo,
        )
        config.validate()
        if args.output_dir.exists() and any(args.output_dir.iterdir()):
            raise ValueError("OUTPUT_DIR_MUST_BE_EMPTY")
        metadata = build_run_metadata(
            args.prepared_dir,
            manifest,
            config,
            status="DRY_RUN_VALIDATED" if args.dry_run else "READY_TO_RUN",
        )
        metadata["record_counts"] = {"train": len(train), "validation": len(validation)}
        if args.dry_run:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            (args.output_dir / "run_metadata.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        else:
            metadata = train_qlora(
                args.prepared_dir,
                args.output_dir,
                config,
                allow_synthetic_demo=args.allow_synthetic_demo,
            )
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
