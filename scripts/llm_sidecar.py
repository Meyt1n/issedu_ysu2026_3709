"""Ollama-compatible local LLM sidecar serving the HCT-402 QLoRA adapter.

Loads the local Qwen3-4B base model (4-bit NF4) plus the fine-tuned LoRA
adapter once at startup and exposes the two Ollama endpoints the backend
assistant uses (``GET /api/tags``, ``POST /api/chat``). This replaces a
real Ollama install, which is currently crash-looping on this machine and
cannot serve safetensors adapters directly anyway.

The assistant backend (``app.tool_call.run_assistant``) expects the reply
content to be a JSON object matching ``HealthAssistantOutput`` (answer /
sources / confidence / escalate), so when the caller does not provide its
own system prompt we inject one that pins the output contract and the
medical boundary ("no diagnosis / prescription / dosage decisions").

Run inside a GPU inference environment you maintain locally
(do not hard-code another developer's disk path):

    <your-gpu-python> scripts/llm_sidecar.py \
        --base "<repo-external>/base-model" \
        --adapter "<repo-external>/adapter" \
        --port 11435

Results are teaching-demo output and never a medical decision.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("llm-sidecar")

MODEL_NAME = os.environ.get("HCT_LLM_MODEL_NAME", "hct402-qlora-v5")

DEFAULT_SYSTEM_PROMPT = (
    "你是「家健镜」家庭健康助手，运行在家庭本地设备上，服务于家庭照护的教学演示。"
    "回答要求：\n"
    "1. 只依据用户消息中提供的本地事实、规则结果与文档片段回答；资料不足时明确说「无法判断」。\n"
    "2. 绝不做诊断、开处方、决定用药剂量或建议停药换药；不提供购买链接或外部网址。\n"
    "3. 用温和、口语化的简体中文，先给依据再给解释。\n"
    "4. 输出必须是一个 JSON 对象，且只有 JSON，格式："
    '{"answer": "回答正文", "sources": ["引用的依据标识"], '
    '"confidence": "high|medium|low", "escalate": false}。'
    "紧急情况（如疑似中毒、呼吸困难）时 escalate 设为 true 并提醒联系医务人员。"
)


class Engine:
    """Single-flight wrapper around the quantized base+adapter bundle."""

    def __init__(self, base_path: str, adapter_path: str, device: str) -> None:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        logger.info("loading tokenizer from %s", base_path)
        self.tokenizer = AutoTokenizer.from_pretrained(
            base_path, local_files_only=True, use_fast=True
        )
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        logger.info("loading 4-bit base model (this takes ~1 minute)...")
        quantization = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            base_path,
            local_files_only=True,
            quantization_config=quantization,
            dtype=torch.bfloat16,
            device_map={"": int(device) if device.isdigit() else device},
            low_cpu_mem_usage=True,
        )
        logger.info("attaching adapter %s", adapter_path)
        model = PeftModel.from_pretrained(
            model, adapter_path, local_files_only=True, is_trainable=False
        )
        model.eval()
        self.model = model
        self.torch = torch
        self.lock = threading.Lock()
        logger.info("engine ready: %s", MODEL_NAME)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_new_tokens: int,
    ) -> str:
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,  # matches the v5 training configuration
        )
        inputs = self.tokenizer(
            prompt, return_tensors="pt", truncation=True, max_length=4096
        ).to(self.model.device)
        do_sample = temperature > 0
        with self.lock, self.torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=do_sample,
                temperature=temperature if do_sample else None,
                top_p=0.9 if do_sample else None,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )
        return self.tokenizer.decode(
            output[0, inputs["input_ids"].shape[-1]:], skip_special_tokens=True
        ).strip()


def normalize_messages(raw: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Keep role/content pairs; pin the output contract as the first system.

    Caller-provided system messages (e.g. the backend's member-fact context)
    are merged after the contract prompt so grounding never displaces the
    JSON output requirement or the medical boundary.
    """
    messages = [
        {"role": str(item.get("role", "user")), "content": str(item.get("content", ""))}
        for item in raw
        if item.get("content")
    ]
    system_parts = [DEFAULT_SYSTEM_PROMPT] + [
        message["content"] for message in messages if message["role"] == "system"
    ]
    rest = [message for message in messages if message["role"] != "system"]
    return [{"role": "system", "content": "\n\n".join(system_parts)}, *rest]


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Parse the first JSON object out of generated text (fences tolerated)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for start, character in enumerate(cleaned):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _regex_field(raw_text: str, names: tuple[str, ...]) -> str | None:
    """Pull a string field out of malformed JSON (v5 sometimes emits both)."""
    import re

    for name in names:
        match = re.search(rf'"{name}"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_text)
        if match:
            try:
                return json.loads(f'"{match.group(1)}"')
            except json.JSONDecodeError:
                return match.group(1)
    return None


def _regex_sources(raw_text: str) -> list[str]:
    import re

    match = re.search(r'"sources"\s*:\s*\[([^\]]*)\]', raw_text)
    if not match:
        return []
    items = (item.strip().strip('"') for item in match.group(1).split(","))
    return [item for item in items if item]


def normalize_output(raw_text: str) -> str:
    """Map the v5 output contract onto the assistant's expected schema.

    The v5 adapter was fine-tuned on a ``response``/``status``/``fields``
    contract and occasionally emits malformed JSON; the backend validates
    against ``answer``/``sources``/``confidence``/``escalate``. Parse
    strictly first, then fall back to regex extraction, then wrap free text.
    """
    parsed = extract_json_object(raw_text)
    answer: str | None = None
    sources: list[str] = []
    confidence = "low"
    escalate = False
    if parsed is not None:
        candidate = parsed.get("answer") or parsed.get("response") or parsed.get("content")
        if isinstance(candidate, str) and candidate.strip():
            answer = candidate
        raw_sources = parsed.get("sources")
        if isinstance(raw_sources, list):
            sources = [str(item) for item in raw_sources]
        if parsed.get("confidence") in ("high", "medium", "low"):
            confidence = parsed["confidence"]
        escalate = bool(parsed.get("escalate", False))
    if answer is None:
        answer = _regex_field(raw_text, ("response", "answer"))
        if answer is not None:
            sources = sources or _regex_sources(raw_text)
            regex_confidence = _regex_field(raw_text, ("confidence",))
            if regex_confidence in ("high", "medium", "low"):
                confidence = regex_confidence
    if answer is None:
        answer = raw_text.strip()
    return json.dumps(
        {
            "answer": answer.strip(),
            "sources": sources[:8],
            "confidence": confidence,
            "escalate": escalate,
        },
        ensure_ascii=False,
    )


def build_app(engine: Engine):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI(title="HCT-402 local LLM sidecar", docs_url=None, redoc_url=None)

    @app.get("/api/tags")
    def tags() -> dict:
        return {
            "models": [
                {
                    "name": MODEL_NAME,
                    "model": MODEL_NAME,
                    "details": {
                        "family": "qwen3",
                        "parameter_size": "4B",
                        "quantization_level": "NF4",
                    },
                }
            ]
        }

    @app.post("/api/chat")
    def chat(payload: dict) -> JSONResponse:
        started = time.time()
        messages = normalize_messages(payload.get("messages") or [])
        options = payload.get("options") or {}
        temperature = float(options.get("temperature", 0.3))
        max_new_tokens = int(options.get("num_predict", 512))
        try:
            content = normalize_output(
                engine.chat(messages, temperature=temperature, max_new_tokens=max_new_tokens)
            )
        except Exception as exc:  # surface as HTTP 500, backend degrades cleanly
            logger.exception("generation failed")
            return JSONResponse(status_code=500, content={"error": str(exc)[:200]})
        elapsed = time.time() - started
        logger.info(
            "chat done: %d msgs -> %d chars in %.1fs", len(messages), len(content), elapsed
        )
        return JSONResponse(
            content={
                "model": MODEL_NAME,
                "message": {"role": "assistant", "content": content},
                "done": True,
                "total_duration": int(elapsed * 1e9),
            }
        )

    return app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=os.environ.get("HCT_LLM_BASE_MODEL"))
    parser.add_argument("--adapter", default=os.environ.get("HCT_LLM_ADAPTER"))
    parser.add_argument("--device", default=os.environ.get("HCT_LLM_DEVICE", "0"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11435)
    args = parser.parse_args()
    if not args.base or not args.adapter:
        raise SystemExit("--base and --adapter (or HCT_LLM_BASE_MODEL/HCT_LLM_ADAPTER) required")

    engine = Engine(args.base, args.adapter, args.device)

    import uvicorn

    uvicorn.run(build_app(engine), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
