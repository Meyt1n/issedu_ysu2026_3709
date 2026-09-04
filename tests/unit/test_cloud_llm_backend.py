"""The cloud model backend must be a true drop-in for the local Ollama client.

"Drop-in" is the actual requirement here, so these tests pin the seams that make
it one: the same interface, the same Ollama-shaped return value, the same
``OLLAMA_UNAVAILABLE`` failure string the orchestrator degrades on, and no new
surface for the frontend.  They also pin the safety edges — half-configured
switches stay local, plaintext endpoints are refused, and the API key never
reaches a log line.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.cloud_llm import (
    CloudChatClient,
    cloud_allowed_hosts,
    cloud_backend_enabled,
    is_usable_cloud_endpoint,
)
from app.config import get_settings
from app.tool_call import (
    OllamaClient,
    build_chat_client,
    extract_tool_calls,
    is_loopback_ollama_url,
    model_endpoint_allowed,
)

CLOUD_URL = "https://api.example-llm.test/v1"
API_KEY = "sk-test-secret-value-do-not-log"


def _configure_cloud(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    """Point settings at the cloud backend (patching the live singleton)."""
    settings = get_settings()
    values: dict[str, Any] = {
        "llm_provider": "cloud",
        "llm_api_base_url": CLOUD_URL,
        "llm_api_key": API_KEY,
        "llm_api_model": "test-cloud-model",
    }
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)


def _client(**overrides: Any) -> CloudChatClient:
    kwargs: dict[str, Any] = {
        "base_url": CLOUD_URL,
        "api_key": API_KEY,
        "default_model": "test-cloud-model",
    }
    kwargs.update(overrides)
    return CloudChatClient(**kwargs)


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Route the client's httpx.Client through a mock transport."""
    real_client = httpx.Client

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = _transport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)


# ── backend selection ───────────────────────────────────────────────────


def test_default_deployment_stays_on_the_local_model() -> None:
    """Without explicit opt-in the assistant must remain local-only."""
    assert cloud_backend_enabled() is False
    assert isinstance(build_chat_client("http://localhost:11434"), OllamaClient)


def test_cloud_switch_selects_the_cloud_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_cloud(monkeypatch)

    assert cloud_backend_enabled() is True
    assert isinstance(build_chat_client("http://localhost:11434"), CloudChatClient)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"llm_api_key": ""}, "missing key"),
        ({"llm_api_base_url": ""}, "missing endpoint"),
        ({"llm_api_base_url": "http://api.example-llm.test/v1"}, "plaintext endpoint"),
        ({"llm_provider": "local"}, "switch not enabled"),
    ],
)
def test_half_configured_switch_falls_back_to_local(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any], reason: str
) -> None:
    """A partial switch must degrade to local, not fail every request."""
    _configure_cloud(monkeypatch, **overrides)

    assert cloud_backend_enabled() is False, reason
    assert isinstance(build_chat_client("http://localhost:11434"), OllamaClient)


def test_plaintext_endpoint_is_refused_but_loopback_gateway_is_allowed() -> None:
    """Health facts must not cross a network in the clear."""
    assert is_usable_cloud_endpoint("https://api.example-llm.test/v1") is True
    assert is_usable_cloud_endpoint("http://api.example-llm.test/v1") is False
    # A gateway on this machine never leaves it.
    assert is_usable_cloud_endpoint("http://127.0.0.1:8000/v1") is True
    assert is_usable_cloud_endpoint("ftp://api.example-llm.test") is False


# ── endpoint guard ──────────────────────────────────────────────────────


def test_local_mode_still_blocks_a_public_model_endpoint() -> None:
    """The original loopback guard must survive: this is the local-first rule."""
    assert model_endpoint_allowed("http://localhost:11434") is True
    assert model_endpoint_allowed("https://evil.example.test") is False
    assert is_loopback_ollama_url("https://evil.example.test") is False


def test_cloud_mode_permits_the_configured_remote_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cloud mode is an explicit operator decision, so the guard yields."""
    _configure_cloud(monkeypatch)

    assert model_endpoint_allowed("http://localhost:11434") is True
    # is_loopback_ollama_url keeps its literal meaning; only the gate is
    # mode-aware, so the two must not be conflated.
    assert is_loopback_ollama_url("https://api.example-llm.test") is False


def test_allowed_hosts_cover_endpoint_and_extras(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_cloud(
        monkeypatch, llm_api_extra_allowed_hosts="cdn.example-llm.test, https://alt.example.test"
    )

    hosts = cloud_allowed_hosts()

    assert "api.example-llm.test" in hosts
    assert "cdn.example-llm.test" in hosts
    assert "alt.example.test" in hosts


# ── request translation ─────────────────────────────────────────────────


def test_chat_posts_openai_shape_and_returns_ollama_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller sends Ollama arguments and gets an Ollama envelope back."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "本地照护建议正文。"}}
                ]
            },
        )

    _patch_httpx(monkeypatch, handler)

    result = _client().chat(
        model="local-model-name",
        messages=[{"role": "user", "content": "奶奶血压偏高怎么办"}],
        temperature=0.3,
        max_tokens=800,
    )

    assert seen["url"] == "https://api.example-llm.test/v1/chat/completions"
    assert seen["auth"] == f"Bearer {API_KEY}"
    # The configured cloud model wins: the caller's name is a *local* model the
    # provider would reject.
    assert seen["body"]["model"] == "test-cloud-model"
    assert seen["body"]["stream"] is False
    assert seen["body"]["max_tokens"] == 800
    # Ollama envelope, so extract/parse helpers work unchanged.
    assert result["done"] is True
    assert result["message"]["content"] == "本地照护建议正文。"


def test_vision_content_is_forwarded_only_by_explicitly_enabled_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "文字"}}]},
        )

    _patch_httpx(monkeypatch, handler)
    client = _client(vision_enabled=True)
    image_content = [
        {"type": "text", "text": "请提取图片文字"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]

    client.chat(
        model="m",
        messages=[{"role": "user", "content": image_content}],
        max_tokens=100,
    )

    assert client.vision_enabled is True
    assert seen["body"]["messages"][0]["content"] == image_content


def test_tool_calls_survive_the_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI returns JSON-string arguments; the tool layer must still parse."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        # Ollama tool declarations pass through in OpenAI's shape.
        assert body["tools"][0]["type"] == "function"
        assert body["tools"][0]["function"]["name"] == "retrieve_knowledge"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "retrieve_knowledge",
                                        "arguments": '{"query": "高血压"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    _patch_httpx(monkeypatch, handler)

    raw = _client().chat(
        model="m",
        messages=[{"role": "user", "content": "q"}],
        tools=[{"type": "function", "function": {"name": "retrieve_knowledge", "parameters": {}}}],
    )

    assert extract_tool_calls(raw) == [
        {"name": "retrieve_knowledge", "arguments": {"query": "高血压"}}
    ]


def test_bare_json_schema_is_wrapped_for_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ollama takes a bare schema; OpenAI needs it under ``json_schema``."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    _patch_httpx(monkeypatch, handler)

    _client().chat(
        model="m",
        messages=[{"role": "user", "content": "q"}],
        response_format={"type": "object", "properties": {"answer": {"type": "string"}}},
    )

    fmt = seen["body"]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["schema"]["properties"]["answer"]["type"] == "string"


def test_deepseek_style_provider_gets_json_object_not_a_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DeepSeek's chat/completions accepts only ``json_object``.

    Sending a wrapped ``json_schema`` there is a 400 on *every* synthesis call,
    so the mode must translate rather than pass the schema through.
    """
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    _patch_httpx(monkeypatch, handler)

    _client(response_format_mode="json_object").chat(
        model="m",
        messages=[{"role": "user", "content": "q"}],
        response_format={"type": "object", "properties": {"answer": {"type": "string"}}},
    )

    assert seen["body"]["response_format"] == {"type": "json_object"}


def test_response_format_is_omitted_when_the_gateway_lacks_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator can degrade a feature instead of losing the backend."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _patch_httpx(monkeypatch, handler)

    _client(response_format_mode="none", supports_tools=False).chat(
        model="m",
        messages=[{"role": "user", "content": "q"}],
        tools=[{"type": "function", "function": {"name": "t", "parameters": {}}}],
        response_format={"type": "object"},
    )

    assert "response_format" not in seen["body"]
    assert "tools" not in seen["body"]


def test_rejected_json_contract_retries_without_it_even_with_no_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The synthesis call sends a schema and no tools; a 400 must be recoverable."""
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "response_format" in body:
            return httpx.Response(400, text="response_format is not supported")
        return httpx.Response(200, json={"choices": [{"message": {"content": "回答正文"}}]})

    _patch_httpx(monkeypatch, handler)

    result = _client().chat(
        model="m",
        messages=[{"role": "user", "content": "q"}],
        response_format={"type": "object"},
    )

    assert len(bodies) == 2
    assert "response_format" in bodies[0]
    assert "response_format" not in bodies[1]
    assert result["message"]["content"] == "回答正文"


# ── streaming ───────────────────────────────────────────────────────────


def test_stream_yields_plain_text_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same contract as the local client: bare content strings."""
    frames = [
        'data: {"choices":[{"delta":{"role":"assistant"}}]}',
        'data: {"choices":[{"delta":{"content":"先"}}]}',
        "",
        ": keep-alive",
        'data: {"choices":[{"delta":{"content":"量血压"}}]}',
        "data: [DONE]",
        'data: {"choices":[{"delta":{"content":"never"}}]}',
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="\n".join(frames))

    _patch_httpx(monkeypatch, handler)

    chunks = list(
        _client().chat_stream(model="m", messages=[{"role": "user", "content": "q"}])
    )

    assert chunks == ["先", "量血压"]


def test_stream_cancel_check_stops_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The orchestrator must be able to abandon a generation mid-flight."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text='data: {"choices":[{"delta":{"content":"a"}}]}\n' * 20
        )

    _patch_httpx(monkeypatch, handler)

    with pytest.raises(RuntimeError, match="OLLAMA_CANCELLED"):
        list(
            _client().chat_stream(
                model="m",
                messages=[{"role": "user", "content": "q"}],
                cancel_check=lambda: True,
            )
        )


def test_malformed_stream_frame_does_not_abort_a_good_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="\n".join(
                [
                    "data: {not json",
                    'data: {"choices":[{"delta":{"content":"ok"}}]}',
                    "data: [DONE]",
                ]
            ),
        )

    _patch_httpx(monkeypatch, handler)

    assert list(
        _client().chat_stream(model="m", messages=[{"role": "user", "content": "q"}])
    ) == ["ok"]


# ── failure parity and secret hygiene ───────────────────────────────────


def test_failure_raises_the_same_string_the_orchestrator_degrades_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reusing OLLAMA_UNAVAILABLE is what keeps MODEL_UNAVAILABLE working."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream exploded")

    _patch_httpx(monkeypatch, handler)

    with pytest.raises(RuntimeError, match="OLLAMA_UNAVAILABLE"):
        _client().chat(model="m", messages=[{"role": "user", "content": "q"}])


def test_deterministic_4xx_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bad key or unknown model should fail fast, not stall the caller."""
    attempts: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(401, text="invalid api key")

    _patch_httpx(monkeypatch, handler)

    with pytest.raises(RuntimeError, match="OLLAMA_UNAVAILABLE"):
        _client().chat(model="m", messages=[{"role": "user", "content": "q"}])

    assert len(attempts) == 1


def test_api_key_never_reaches_a_log_line(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An upstream error that echoes the key must not leak it into logs."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=f"bad request for key {API_KEY}")

    _patch_httpx(monkeypatch, handler)

    with caplog.at_level("WARNING"):
        with pytest.raises(RuntimeError):
            _client().chat(model="m", messages=[{"role": "user", "content": "q"}])

    assert API_KEY not in caplog.text
    assert "***" in caplog.text


def test_unreachable_endpoint_reports_unavailable_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Availability probes must not raise: callers treat them as booleans."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    _patch_httpx(monkeypatch, handler)

    assert _client().is_available() is False


def test_missing_key_is_unavailable_without_a_request() -> None:
    assert _client(api_key="").health_check() is False


# ── the switch must stay invisible to clients ───────────────────────────


def test_capabilities_response_is_identical_with_the_cloud_backend_active(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The backend choice is an ops detail: no client may be able to see it.

    ``llm-cloud`` stays declared unavailable on purpose — it describes the
    unbuilt cloud *product* capability, not this internal switch — and no
    endpoint/model/key may appear anywhere in the payload.
    """
    local = client.get("/api/v1/meta/capabilities").json()

    _configure_cloud(monkeypatch)
    assert cloud_backend_enabled() is True
    cloud = client.get("/api/v1/meta/capabilities").json()

    assert cloud == local
    assert "llm-cloud" in cloud["unavailable"]
    serialized = json.dumps(cloud).lower()
    for leak in ("example-llm", API_KEY.lower(), "llm_api", "llm_provider"):
        assert leak not in serialized
