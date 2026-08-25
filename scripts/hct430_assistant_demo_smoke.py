#!/usr/bin/env python3
"""HCT-430 assistant demo smoke — honest local evidence without claiming R3.

Runs checks that can complete without a live browser:

1. Import/orchestration invariants (greeting path, classifier lexicon, agents catalog helpers)
2. Optional live HTTP probes when HCT_API_BASE is set
3. Optional Ollama loopback probe when OLLAMA_BASE_URL is reachable

Writes a markdown evidence note under docs/reviews/. Never embeds real health data.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src" / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "src" / "api"))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def _ok(label: str, detail: str = "") -> dict[str, Any]:
    return {"status": "pass", "label": label, "detail": detail}


def _skip(label: str, detail: str) -> dict[str, Any]:
    return {"status": "skip", "label": label, "detail": detail}


def _fail(label: str, detail: str) -> dict[str, Any]:
    return {"status": "fail", "label": label, "detail": detail}


def run_offline_checks() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        from ai.safety.classifier import classify_question_lexicon, merge_query_types

        from app.local_agents import plan_agent_execution
        from app.tool_call import classify_question, is_loopback_ollama_url

        assert classify_question("你好") == "GENERAL"
        assert classify_question("好像吃错药了怎么办？") == "MEDICATION_SAFETY"
        assert merge_query_types("GENERAL", "MEDICATION_SAFETY") == "MEDICATION_SAFETY"
        assert classify_question_lexicon("呼吸困难怎么办") == "URGENT"
        assert is_loopback_ollama_url("http://127.0.0.1:11434")
        assert not is_loopback_ollama_url("https://ollama.example.com")
        plan = plan_agent_execution("GENERAL", household_id=None, member_id=None)
        assert plan["database"].run is False
        # GENERAL now tries local knowledge; web search follows the opt-in.
        assert plan["knowledge"].run is True
        assert plan["web_search"].run is False
        assert plan["web_search"].reason_code == "NOT_OPTED_IN"
        opted_in = plan_agent_execution(
            "GENERAL", household_id=None, member_id=None, allow_network_search=True
        )
        assert opted_in["web_search"].run is True
        results.append(
            _ok("offline.classifier_and_plan", "greeting/GENERAL/MEDICATION_SAFETY/URGENT + plan")
        )
    except Exception as exc:  # noqa: BLE001
        results.append(_fail("offline.classifier_and_plan", str(exc)[:240]))
    return results


def run_http_checks(base_url: str) -> list[dict[str, Any]]:
    import urllib.error
    import urllib.request

    results: list[dict[str, Any]] = []
    base = base_url.rstrip("/")

    def get(path: str) -> tuple[int, Any]:
        req = urllib.request.Request(f"{base}{path}", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310 — operator-provided base
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body

    try:
        status, payload = get("/health")
        if status == 200:
            health_status = payload.get("status") if isinstance(payload, dict) else status
            results.append(_ok("http.health", f"status={health_status}"))
        else:
            results.append(_fail("http.health", f"HTTP {status}"))
    except Exception as exc:  # noqa: BLE001
        results.append(_fail("http.health", str(exc)[:240]))
        return results

    try:
        status, payload = get("/api/v1/assistant/agents")
        if status != 200 or not isinstance(payload, dict):
            results.append(_fail("http.agents_catalog", f"HTTP {status}"))
        else:
            agents = payload.get("agents") or payload.get("items") or []
            local_flags = (
                [bool(item.get("local", True)) for item in agents]
                if isinstance(agents, list)
                else []
            )
            all_local = all(local_flags) if local_flags else payload.get("all_agents_local", True)
            agent_count = len(agents) if isinstance(agents, list) else "n/a"
            results.append(
                _ok(
                    "http.agents_catalog",
                    f"agents={agent_count} all_local={all_local} "
                    f"web_search_ready={payload.get('web_search_ready')}",
                )
            )
    except urllib.error.HTTPError as exc:
        results.append(_fail("http.agents_catalog", f"HTTP {exc.code}"))
    except Exception as exc:  # noqa: BLE001
        results.append(_fail("http.agents_catalog", str(exc)[:240]))

    # Greeting multi-agent path should not require Ollama.
    try:
        body = json.dumps(
            {
                "messages": [{"role": "user", "content": "你好"}],
                "agent_mode": "multi_agent",
                "allow_network_search": False,
                "max_tokens": 64,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/api/v1/assistant/chat",
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Actor-Id": "demo-smoke-actor",
                "X-Access-Purpose": "family-care",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
        answer = str(payload.get("answer") or "")
        if answer and payload.get("orchestration_mode") == "multi_agent":
            results.append(
                _ok(
                    "http.greeting_multi_agent",
                    f"degraded={payload.get('degraded')} query_type={payload.get('query_type')} "
                    f"network_used={payload.get('network_used')}",
                )
            )
        else:
            results.append(
                _fail("http.greeting_multi_agent", f"unexpected payload keys={list(payload)[:12]}")
            )
    except Exception as exc:  # noqa: BLE001
        results.append(
            _skip("http.greeting_multi_agent", f"auth or API unavailable: {str(exc)[:180]}")
        )

    return results


def run_ollama_checks(base_url: str, model: str) -> list[dict[str, Any]]:
    import urllib.error
    import urllib.request

    results: list[dict[str, Any]] = []
    base = base_url.rstrip("/")
    try:
        req = urllib.request.Request(f"{base}/api/tags", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
        names = [item.get("name") for item in payload.get("models", []) if isinstance(item, dict)]
        has_configured = model in names or model == "unavailable"
        results.append(_ok("ollama.tags", f"models={len(names)} has_configured={has_configured}"))
        listed = model in names or any(model in (n or "") for n in names)
        if model and model != "unavailable" and not listed:
            results.append(
                _skip("ollama.model", f"configured model {model!r} not listed; chat probe skipped")
            )
            return results
        if model == "unavailable":
            results.append(_skip("ollama.chat", "OLLAMA_MODEL=unavailable"))
            return results
        chat_body = json.dumps(
            {
                "model": model,
                "stream": False,
                "think": False,
                "messages": [{"role": "user", "content": "用四个字回答：你好"}],
                "options": {"temperature": 0, "num_predict": 16},
            }
        ).encode("utf-8")
        chat_req = urllib.request.Request(
            f"{base}/api/chat",
            data=chat_body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(chat_req, timeout=60) as resp:  # noqa: S310
            chat_payload = json.loads(resp.read().decode("utf-8"))
        content = ((chat_payload.get("message") or {}).get("content") or "").strip()
        if content:
            results.append(_ok("ollama.chat", f"reply_chars={len(content)} (text redacted)"))
        else:
            results.append(_fail("ollama.chat", "empty content"))
    except urllib.error.URLError as exc:
        results.append(_skip("ollama.tags", f"unreachable: {exc}"))
    except Exception as exc:  # noqa: BLE001
        results.append(_skip("ollama.probe", str(exc)[:240]))
    return results


def render_report(results: list[dict[str, Any]], *, out_path: Path) -> None:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    passed = sum(1 for item in results if item["status"] == "pass")
    failed = sum(1 for item in results if item["status"] == "fail")
    skipped = sum(1 for item in results if item["status"] == "skip")
    lines = [
        "# HCT-430 助手演示冒烟记录",
        "",
        f"- 生成时间（UTC）：{now}",
        "- 脚本：`scripts/hct430_assistant_demo_smoke.py`",
        f"- 汇总：pass={passed} fail={failed} skip={skipped}",
        "",
        "## 结论边界",
        "",
        "- 本记录只证明本机可自动完成的冒烟项；"
        "**不**替代维护者 R3、真实浏览器端到端、MySQL 全家演示或回滚演练签署。",
        "- 未写入真实健康数据、密钥或完整模型输出正文。",
        "",
        "## 检查项",
        "",
        "| 状态 | 项 | 说明 |",
        "|---|---|---|",
    ]
    for item in results:
        detail = (item.get("detail") or "").replace("|", "\\|")
        lines.append(f"| {item['status']} | `{item['label']}` | {detail} |")
    lines.extend(
        [
            "",
            "## 仍需维护者完成",
            "",
            "- 正式环境 R3（网络出口、隐私、模型边界）复核",
            "- 浏览器 Web + APP 联机演示录屏",
            "- 联网搜索双重开关与域名白名单现场复核（默认仍关闭）",
            "- 回滚：`AGENT_WEB_SEARCH_ENABLED=false` / `agent_mode=single`",
            "",
        ]
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=os.environ.get("HCT_API_BASE", ""))
    parser.add_argument("--ollama-base", default=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--ollama-model", default=os.environ.get("OLLAMA_MODEL", "unavailable"))
    parser.add_argument(
        "--out",
        default=str(ROOT / "docs" / "reviews" / "HCT-430-助手演示冒烟记录.md"),
    )
    args = parser.parse_args()

    results = run_offline_checks()
    if args.api_base:
        results.extend(run_http_checks(args.api_base))
    else:
        results.append(_skip("http.*", "HCT_API_BASE / --api-base not set"))
    results.extend(run_ollama_checks(args.ollama_base, args.ollama_model))

    out_path = Path(args.out)
    render_report(results, out_path=out_path)
    print(out_path)
    failed = sum(1 for item in results if item["status"] == "fail")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
