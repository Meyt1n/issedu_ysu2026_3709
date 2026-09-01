"""Cloud model backend: a drop-in replacement for the local Ollama client.

The assistant's default posture is local-only (HCT-004 / HCT-430): every model
call stays on this machine.  Local small models are, however, not always strong
enough for the harder care questions, so an operator may point the *same*
pipeline at an OpenAI-compatible chat-completions endpoint instead.

The switch is deliberately ops-only (``LLM_PROVIDER=cloud`` in ``.env``) and has
no UI: the frontend, the orchestrator, the tool contract, the safety gates and
the response schema are all untouched.  ``CloudChatClient`` mirrors
``OllamaClient``'s interface exactly — same method names, same keyword
arguments, same Ollama-shaped return value, and the same
``RuntimeError("OLLAMA_UNAVAILABLE: ...")`` on failure so the existing
``MODEL_UNAVAILABLE`` degrade paths keep working without a single new branch.

Turning this on is an egress decision, not just a quality one: prompts can carry
member health facts, so the endpoint host must also be reachable under the
deployment's egress policy.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Generator
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Kept identical to tool_call's retry shape so both backends degrade alike.
MAX_RETRIES = 2
RETRY_BACKOFF = 2
DEFAULT_TIMEOUT = 60.0

# The orchestrator keys its structured degrade on this prefix.  Reusing it is
# what makes this class a true drop-in rather than a parallel error taxonomy.
UNAVAILABLE_PREFIX = "OLLAMA_UNAVAILABLE"

# Distinguishes "stream finished" from "this chunk carried no text", which an
# empty string cannot express.
_DONE = object()


def _redact(text: str, secret: str) -> str:
    """Remove the API key from anything that may reach a log line."""
    if secret and secret in text:
        text = text.replace(secret, "***")
    return text


def cloud_endpoint_host(base_url: str) -> str:
    """Host (with port when explicit) of the configured endpoint, lowercased."""
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if not host:
        return ""
    return f"{host}:{parsed.port}" if parsed.port else host


def is_usable_cloud_endpoint(base_url: str) -> bool:
    """Whether the endpoint is a well-formed HTTPS URL.

    Plain HTTP is refused: the payload can contain member health facts, so it
    must not cross a network in the clear.  A loopback HTTP gateway is the one
    sanctioned exception — that traffic never leaves the machine.
    """
    parsed = urlparse(base_url)
    if parsed.scheme == "https":
        return bool(parsed.hostname)
    if parsed.scheme == "http":
        return parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    return False


def _tools_payload(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Translate Ollama tool declarations to OpenAI's ``tools`` array.

    Ollama already uses OpenAI's ``{"type": "function", "function": {...}}``
    shape, so well-formed entries pass through untouched; bare declarations are
    wrapped so either style works.
    """
    if not tools:
        return None
    payload: list[dict[str, Any]] = []
    for tool in tools:
        if isinstance(tool, dict) and tool.get("type") == "function" and "function" in tool:
            payload.append(tool)
        elif isinstance(tool, dict):
            payload.append({"type": "function", "function": tool})
    return payload or None


def _response_format_payload(
    response_format: dict[str, Any] | None,
    mode: str = "json_schema",
) -> dict[str, Any] | None:
    """Translate Ollama's ``format`` schema to the provider's JSON contract.

    Ollama takes a bare JSON Schema, but providers differ on what they accept:

    * ``json_schema`` — OpenAI-style strict schema.  Strict mode itself is left
      off (it demands ``additionalProperties: false`` plus an exhaustive
      ``required`` list), so the application layer keeps validating exactly as
      it does for Ollama.
    * ``json_object`` — valid-JSON-only, which is all DeepSeek's
      ``chat/completions`` accepts.  The schema is dropped; the prompt already
      states the contract and the app layer still validates the result.
    * ``none`` — omit the field entirely.

    Sending a ``json_schema`` to a ``json_object``-only provider is a hard 400
    on every synthesis call, which is why this is explicit per provider.
    """
    if response_format is None:
        return None
    normalized = (mode or "json_schema").strip().lower()
    if normalized == "none":
        return None
    # An explicitly-typed request from the caller is passed through as given.
    if response_format.get("type") in {"json_object", "json_schema", "text"}:
        return response_format
    if normalized == "json_object":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {"name": "assistant_reply", "schema": response_format},
    }


def _ollama_shaped(choice_message: dict[str, Any]) -> dict[str, Any]:
    """Wrap an OpenAI choice message in the Ollama ``/api/chat`` envelope.

    ``extract_tool_calls`` already normalizes both Ollama's dict arguments and
    OpenAI's JSON-string arguments, so tool calls pass through as received.
    """
    message: dict[str, Any] = {
        "role": choice_message.get("role") or "assistant",
        "content": choice_message.get("content") or "",
    }
    tool_calls = choice_message.get("tool_calls")
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"message": message, "done": True}


class CloudChatClient:
    """OpenAI-compatible chat backend with ``OllamaClient``'s exact interface."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        default_model: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        max_tokens_ceiling: int = 2048,
        supports_tools: bool = True,
        response_format_mode: str = "json_schema",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._default_model = default_model
        self._timeout = timeout
        self._max_tokens_ceiling = max_tokens_ceiling
        self._supports_tools = supports_tools
        self._response_format_mode = response_format_mode
        self._available: bool | None = None

    # ── endpoint helpers ────────────────────────────────────────────────
    @property
    def _completions_url(self) -> str:
        """Accept a base with or without the ``/v1`` suffix."""
        base = self.base_url
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _resolve_model(self, model: str) -> str:
        """Prefer the cloud model name; fall back to the caller's request.

        Callers pass ``settings.ollama_model``, which names a *local* model that
        the cloud provider will not recognise, so the configured cloud model
        wins whenever it is set.
        """
        return self._default_model or model

    # ── availability (mirrors OllamaClient) ─────────────────────────────
    def health_check(self) -> bool:
        """Treat a reachable, authenticated endpoint as available.

        ``/models`` is the OpenAI-compatible probe.  Gateways that do not expose
        it still count as available when they answer at all (any non-5xx), since
        a 404 on ``/models`` says nothing about chat completions.
        """
        if not self._api_key or not is_usable_cloud_endpoint(self.base_url):
            self._available = False
            return False
        base = self.base_url
        models_url = base if base.endswith("/models") else (
            f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
        )
        try:
            with httpx.Client(timeout=min(self._timeout, 10.0), trust_env=False) as client:
                resp = client.get(models_url, headers=self._headers())
            self._available = resp.status_code < 500
            return self._available
        except Exception as exc:  # noqa: BLE001 — availability must not raise
            logger.warning(
                "Cloud model endpoint unreachable: %s",
                _redact(str(exc)[:160], self._api_key),
            )
            self._available = False
            return False

    def is_available(self) -> bool:
        if self._available is None:
            return self.health_check()
        return self._available

    # ── chat (mirrors OllamaClient.chat) ────────────────────────────────
    def _build_payload(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
        stream: bool,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._resolve_model(model),
            "messages": messages,
            "stream": stream,
            "temperature": temperature,
            "max_tokens": min(max_tokens, self._max_tokens_ceiling),
        }
        if self._supports_tools:
            tool_payload = _tools_payload(tools)
            if tool_payload:
                payload["tools"] = tool_payload
        fmt = _response_format_payload(response_format, self._response_format_mode)
        if fmt is not None:
            payload["response_format"] = fmt
        return payload

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.6,
        max_tokens: int = 1536,
        timeout: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send one chat completion and return it in Ollama's response shape."""
        payload = self._build_payload(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            response_format=response_format,
        )

        last_error: str | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=timeout or self._timeout, trust_env=False) as client:
                    resp = client.post(
                        self._completions_url, json=payload, headers=self._headers()
                    )
                    resp.raise_for_status()
                    data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    last_error = "EMPTY_CHOICES"
                    break
                self._available = True
                return _ollama_shaped(choices[0].get("message") or {})
            except httpx.TimeoutException:
                last_error = "TIMEOUT"
                logger.warning("Cloud model request timed out (attempt %d)", attempt + 1)
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                last_error = f"HTTP_{status_code}"
                detail = _redact(exc.response.text[:200].replace("\n", " "), self._api_key)
                logger.warning(
                    "Cloud model HTTP error %s (attempt %d): %s", status_code, attempt + 1, detail
                )
                # Deterministic compatibility retry (same idea as the local
                # client).  Providers vary in what JSON contract they accept —
                # DeepSeek's chat/completions takes only ``json_object``, and
                # some gateways reject any schema alongside ``tools``.  Drop the
                # optional contract once and let the app layer validate, which
                # it does for the local model anyway.  This is deliberately not
                # gated on ``tools``: the synthesis call sends a schema with no
                # tools, and gating there turned a recoverable 400 into a hard
                # failure of every answer.
                if status_code == 400 and "response_format" in payload:
                    payload.pop("response_format", None)
                    logger.info("Retrying cloud request without response_format")
                    continue
                # A deterministic 4xx (bad key, unknown model) will not improve
                # by retrying; fail fast so the caller can degrade.
                if 400 <= status_code < 500 and status_code not in (408, 429):
                    break
            except Exception as exc:  # noqa: BLE001 — parity with OllamaClient
                last_error = _redact(str(exc)[:120], self._api_key)
                logger.warning(
                    "Cloud model connection error (attempt %d): %s", attempt + 1, last_error
                )

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF**attempt)

        self._available = False
        logger.error("Cloud model failed after %d attempts: %s", MAX_RETRIES + 1, last_error)
        raise RuntimeError(f"{UNAVAILABLE_PREFIX}: {last_error}")

    # ── streaming (mirrors OllamaClient.chat_stream) ────────────────────
    def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.6,
        max_tokens: int = 1536,
        timeout: float | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Generator[str, None, None]:
        """Yield answer text chunks, translating OpenAI SSE deltas.

        Same contract as the local client: plain content strings, and
        ``cancel_check`` polled between chunks so the orchestrator can abandon a
        generation without waiting for it to finish.
        """
        payload = self._build_payload(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        try:
            with httpx.Client(timeout=timeout or self._timeout, trust_env=False) as client:
                with client.stream(
                    "POST", self._completions_url, json=payload, headers=self._headers()
                ) as resp:
                    resp.raise_for_status()
                    if cancel_check is not None and cancel_check():
                        resp.close()
                        raise RuntimeError("OLLAMA_CANCELLED")
                    for line in resp.iter_lines():
                        if cancel_check is not None and cancel_check():
                            resp.close()
                            raise RuntimeError("OLLAMA_CANCELLED")
                        chunk = self._sse_content(line)
                        if chunk is _DONE:
                            break
                        if chunk:
                            yield str(chunk)
        except httpx.HTTPError as exc:
            detail = _redact(str(exc)[:120], self._api_key)
            logger.warning("Cloud model stream unavailable: %s", detail)
            raise RuntimeError(f"{UNAVAILABLE_PREFIX}: {detail}") from exc
        self._available = True

    @staticmethod
    def _sse_content(line: str) -> object:
        """Extract delta text from one SSE line.

        Returns ``_DONE`` at end of stream, ``""`` for keep-alives and non-text
        frames (role-only openers, tool-call deltas, usage tails).  Malformed
        JSON is skipped rather than aborting a stream that is otherwise fine.
        """
        if not line:
            return ""
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line:
            return ""
        if line == "[DONE]":
            return _DONE
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return ""
        choices = data.get("choices") or []
        if not choices:
            return ""
        choice = choices[0]
        delta = choice.get("delta") or {}
        content = delta.get("content")
        if content:
            return content
        # Some gateways send the whole message instead of deltas.
        message = choice.get("message") or {}
        return message.get("content") or ""


# ── backend selection ───────────────────────────────────────────────────


def cloud_backend_enabled() -> bool:
    """Whether a *usable* cloud backend is configured.

    Every requirement is checked here so a half-configured switch (provider set
    but no key, or an http:// endpoint) falls back to the local model instead of
    failing every request at call time.
    """
    from app.config import get_settings

    settings = get_settings()
    if settings.llm_provider.strip().lower() != "cloud":
        return False
    if not settings.llm_api_key.strip() or not settings.llm_api_base_url.strip():
        logger.warning("LLM_PROVIDER=cloud but API key or base URL is missing; staying local")
        return False
    if not is_usable_cloud_endpoint(settings.llm_api_base_url.strip()):
        logger.warning("LLM_API_BASE_URL must be https (or loopback http); staying local")
        return False
    return True


def build_cloud_client() -> CloudChatClient:
    """Construct the cloud client from settings. Call only when enabled."""
    from app.config import get_settings

    settings = get_settings()
    return CloudChatClient(
        base_url=settings.llm_api_base_url.strip(),
        api_key=settings.llm_api_key.strip(),
        default_model=settings.llm_api_model.strip(),
        timeout=float(settings.llm_api_timeout_seconds),
        max_tokens_ceiling=int(settings.llm_api_max_tokens),
        supports_tools=bool(settings.llm_api_supports_tools),
        response_format_mode=settings.llm_api_response_format_mode,
    )


def cloud_allowed_hosts() -> set[str]:
    """Hosts the cloud backend may reach: the endpoint plus any extras."""
    from app.config import get_settings

    settings = get_settings()
    hosts = {cloud_endpoint_host(settings.llm_api_base_url.strip())}
    for extra in settings.llm_api_extra_allowed_hosts.split(","):
        host = cloud_endpoint_host(extra.strip() if "://" in extra else f"https://{extra.strip()}")
        if host:
            hosts.add(host)
    return {host for host in hosts if host}
