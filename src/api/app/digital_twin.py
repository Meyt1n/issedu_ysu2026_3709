"""HCT-519: family digital-twin memory and term-vector projection.

This module keeps model-discovered chat statements separate from the immutable
health-event ledger.  The model may create ``UNCONFIRMED`` memory rows, but
only an explicit human confirmation can promote a disease, medicine, allergy,
or plan into a confirmed health event.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.event_service import append_health_event_transaction
from app.knowledge import KnowledgeChunk, KnowledgeDocument, _check_permission, _tf
from app.models import DigitalTwinMemory, Household, Member, new_id
from app.schemas import HealthEventCreate
from app.tool_call import build_chat_client

logger = logging.getLogger(__name__)

MEMORY_CATEGORIES = frozenset({"PROFILE", "DISEASE", "MEDICATION", "ALLERGY", "PLAN", "NOTE"})
MEMORY_STATUSES = frozenset({"UNCONFIRMED", "CONFIRMED", "REJECTED"})

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "memories": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "member_name": {"type": ["string", "null"]},
                    "category": {
                        "type": "string",
                        "enum": ["PROFILE", "DISEASE", "MEDICATION", "ALLERGY", "PLAN", "NOTE"],
                    },
                    "label": {"type": "string"},
                    "value": {"type": "string"},
                    "detail": {"type": ["string", "null"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["member_name", "category", "label", "value", "detail", "confidence"],
            },
        }
    },
    "required": ["memories"],
    "additionalProperties": False,
}

_EXTRACTION_SYSTEM = (
    "你是家庭健康档案的事实抽取器。只分析用户消息，不分析助手回复，不把助手的建议、"
    "猜测或知识库内容当成事实。抽取用户明确说出的家庭成员信息、疾病、药品、过敏史、"
    "用药计划和其它值得长期记住的健康记录。把提供的用户聊天记录作为待索引语料，"
    "综合多轮上下文消解姓名和代词，并从任意一条用户原话中提取可长期保存的信息。"
    "每项都必须能回查到用户原文；不确定、推测、提问中的假设、否定句、已撤回或被后文"
    "明确纠正的信息不要抽取。返回一个 JSON 对象，不要输出解释。"
)


def _now() -> datetime:
    return datetime.now(UTC)


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _user_messages(messages: Iterable[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = _clean(message.get("content"), 2400)
        if content:
            result.append(content)
    return result[-24:]


def _json_object(content: Any) -> dict[str, Any] | None:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = text.removeprefix("```").removeprefix("json").removesuffix("```").strip()
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _resolve_member_id(
    member_hint: Any,
    *,
    selected_member: Member,
    members: list[Member],
) -> str:
    hint = _clean(member_hint, 120)
    if not hint or hint in {"selected", "当前成员", "当前人"}:
        return selected_member.id
    normalized = hint.casefold()
    for member in members:
        name = member.display_name.strip()
        if name.casefold() == normalized:
            return member.id
    for member in members:
        name = member.display_name.strip()
        if normalized in name.casefold() or name.casefold() in normalized:
            return member.id
    # The prompt tells the model to use a household member name when it knows
    # one.  A residual pronoun is safest when scoped to the selected member.
    return selected_member.id


def _evidence_for(value: str, messages: list[str]) -> str:
    needle = value.casefold()
    for message in reversed(messages):
        if needle and needle in message.casefold():
            return message[:600]
    return (messages[-1] if messages else "")[:600]


def _grounded_in_history(value: str, messages: list[str]) -> bool:
    """Reject model candidates that cannot be traced to a user-authored turn."""
    normalized_value = value.casefold()
    value_terms = set(_tf(normalized_value))
    for message in messages:
        normalized_message = message.casefold()
        if normalized_value in normalized_message:
            return True
        message_terms = set(_tf(normalized_message))
        if value_terms and value_terms.intersection(message_terms):
            return True
    return False


def _extract_candidates(
    messages: list[str],
    *,
    members: list[Member],
    selected_member: Member,
    model: str,
    timeout: float,
) -> list[dict[str, Any]]:
    if not messages:
        return []
    member_names = "、".join(member.display_name for member in members) or "未提供"
    transcript = "\n".join(f"用户第 {index + 1} 条：{text}" for index, text in enumerate(messages))
    prompt = (
        f"家庭成员名单：{member_names}\n"
        f"当前对话成员：{selected_member.display_name}\n"
        "member_name 必须填写名单中的成员姓名；如果是当前成员的‘我/他/她’，填写当前成员。"
        "label 用‘称呼’、‘年龄’、‘性别’、‘疾病’、‘药品’、‘过敏史’、‘用药计划’或‘家庭记录’。"
        "value 只填被用户明确陈述的短值，detail 可填用户原文中的规格、剂量或频次；"
        "不要自行补充剂量。请索引下方全部用户消息；同一事实只返回一次，若后文明确纠正"
        "前文，以后文为准。\n"
        "严格只输出以下结构的 JSON 对象；顶层必须是 memories 数组，每个明确事实单独一项，"
        "六个字段都必须存在："
        '{"memories":[{"member_name":"名单内姓名","category":"PROFILE|DISEASE|MEDICATION|ALLERGY|PLAN|NOTE",'
        '"label":"字段名","value":"短值","detail":"没有则为空字符串","confidence":0.95}]}。'
        '没有可抽取内容时输出 {"memories":[]}。不要输出单个事实对象或 Markdown。\n'
        f"用户消息：\n{transcript}"
    )
    from app.config import get_settings

    settings = get_settings()
    client = build_chat_client(settings.ollama_base_url)
    raw = client.chat(
        model=model,
        messages=[
            {"role": "system", "content": _EXTRACTION_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        tools=None,
        temperature=0.0,
        max_tokens=900,
        timeout=timeout,
        response_format=EXTRACTION_SCHEMA,
    )
    parsed = _json_object((raw.get("message") or {}).get("content"))
    raw_items = parsed.get("memories") if parsed else []
    if not isinstance(raw_items, list):
        return []

    candidates: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        category = _clean(item.get("category"), 32).upper()
        label = _clean(item.get("label"), 120)
        value = _clean(item.get("value"), 500)
        if category not in MEMORY_CATEGORIES or not label or not value:
            continue
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence <= 0.0:
            continue
        member_id = _resolve_member_id(
            item.get("member_name"),
            selected_member=selected_member,
            members=members,
        )
        candidates.append(
            {
                "member_id": member_id,
                "category": category,
                "label": label,
                "value": value,
                "detail": _clean(item.get("detail"), 360),
                "confidence": confidence,
                "evidence_excerpt": _evidence_for(value, messages),
            }
        )
    return candidates


def capture_chat_memories(
    session: Session,
    *,
    messages: list[dict[str, Any]],
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
    assistant_session_id: str | None,
    access_purpose: str | None = None,
) -> dict[str, Any]:
    """Extract and persist unconfirmed memory without breaking chat replies."""
    empty = {"status": "NO_CANDIDATES", "saved_count": 0, "updated_count": 0, "items": []}
    if not household_id or not member_id:
        return empty
    household = session.get(Household, household_id)
    selected_member = session.get(Member, member_id)
    if (
        household is None
        or selected_member is None
        or selected_member.household_id != household_id
        or household.deleted_at is not None
        or selected_member.deleted_at is not None
    ):
        return empty

    user_messages = _user_messages(messages)
    if not user_messages:
        return empty
    from app.security import has_member_read_access

    if not (
        household.created_by == actor_id
        or has_member_read_access(session, household, member_id, actor_id, access_purpose)
    ):
        return {"status": "ACCESS_DENIED", "saved_count": 0, "updated_count": 0, "items": []}

    from app.config import get_settings

    settings = get_settings()
    model = settings.llm_api_model.strip() or settings.ollama_model
    visible_members = [selected_member]
    if household.created_by == actor_id:
        visible_members = list(
            session.scalars(
                select(Member)
                .where(
                    Member.household_id == household_id,
                    Member.deleted_at.is_(None),
                )
                .order_by(Member.created_at, Member.id)
            ).all()
        )
    try:
        candidates = _extract_candidates(
            user_messages,
            members=visible_members,
            selected_member=selected_member,
            model=model,
            timeout=min(float(settings.ollama_timeout_seconds), 30.0),
        )
    except Exception as exc:  # noqa: BLE001 — memory capture is best effort
        logger.warning(
            "DIGITAL_TWIN_MEMORY_CAPTURE_FAILED actor=%s reason=%s", actor_id, type(exc).__name__
        )
        return {"status": "MODEL_UNAVAILABLE", "saved_count": 0, "updated_count": 0, "items": []}

    candidates = [
        candidate
        for candidate in candidates
        if _grounded_in_history(candidate["value"], user_messages)
    ]
    if not candidates:
        return empty

    captured_at = _now()
    all_memories = list(
        session.scalars(
            select(DigitalTwinMemory).where(DigitalTwinMemory.household_id == household_id)
        ).all()
    )
    saved = 0
    updated = 0
    response_items: list[dict[str, Any]] = []
    for candidate in candidates:
        source_digest = _digest(candidate["evidence_excerpt"])
        existing = next(
            (
                memory
                for memory in all_memories
                if memory.member_id == candidate["member_id"]
                and memory.category == candidate["category"]
                and memory.value.strip().casefold() == candidate["value"].strip().casefold()
            ),
            None,
        )
        if existing is not None:
            if existing.status == "REJECTED":
                continue
            # The full transcript is replayed on every turn. The same source
            # excerpt is an idempotent re-index, not a new occurrence.
            if existing.source_digest == source_digest:
                continue
            existing.last_seen_at = captured_at
            existing.updated_at = captured_at
            existing.occurrence_count = int(existing.occurrence_count or 0) + 1
            existing.source_digest = source_digest
            existing.source_session_id = (
                _clean(assistant_session_id, 64) or existing.source_session_id
            )
            if existing.status == "UNCONFIRMED":
                existing.evidence_excerpt = candidate["evidence_excerpt"]
                existing.attributes = {"detail": candidate["detail"]}
                existing.confidence = max(
                    float(existing.confidence or 0.0), candidate["confidence"]
                )
            updated += 1
            response_items.append(
                {
                    "id": existing.id,
                    "label": existing.label,
                    "value": existing.value,
                    "status": existing.status,
                }
            )
            continue

        memory = DigitalTwinMemory(
            id=new_id(),
            household_id=household_id,
            member_id=candidate["member_id"],
            category=candidate["category"],
            label=candidate["label"],
            value=candidate["value"],
            attributes={"detail": candidate["detail"]},
            source_kind="CHAT",
            source_session_id=_clean(assistant_session_id, 64) or None,
            source_digest=source_digest,
            evidence_excerpt=candidate["evidence_excerpt"],
            term_vector=_tf(f"{candidate['label']} {candidate['value']} {candidate['detail']}"),
            confidence=candidate["confidence"],
            status="UNCONFIRMED",
            occurrence_count=1,
            first_seen_at=captured_at,
            last_seen_at=captured_at,
            created_by=actor_id,
        )
        session.add(memory)
        session.flush()
        all_memories.append(memory)
        saved += 1
        response_items.append(
            {"id": memory.id, "label": memory.label, "value": memory.value, "status": memory.status}
        )

    return {
        "status": "CAPTURED" if saved or updated else "NO_CANDIDATES",
        "saved_count": saved,
        "updated_count": updated,
        "items": response_items[:12],
    }


def _vector_similarity(left: dict[str, Any] | None, right: dict[str, Any] | None) -> float:
    a = {
        str(key): float(value)
        for key, value in (left or {}).items()
        if isinstance(value, (int, float))
    }
    b = {
        str(key): float(value)
        for key, value in (right or {}).items()
        if isinstance(value, (int, float))
    }
    if not a or not b:
        return 0.0
    dot = sum(value * b.get(key, 0.0) for key, value in a.items())
    left_norm = math.sqrt(sum(value * value for value in a.values()))
    right_norm = math.sqrt(sum(value * value for value in b.values()))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _vector_terms(vector: dict[str, Any] | None, limit: int = 8) -> list[str]:
    values = [(str(key), float(value)) for key, value in (vector or {}).items()]
    values.sort(key=lambda item: (-item[1], item[0]))
    return [key for key, _ in values[:limit]]


def _stable_unit(seed: str, offset: int) -> float:
    digest = hashlib.sha256(f"{seed}:{offset}".encode()).digest()
    return (digest[offset] / 255.0) * 2.0 - 1.0


def _projection(
    kind: str,
    node_id: str,
    index: int,
    total: int,
    member_position: tuple[float, float, float] | None = None,
) -> dict[str, float]:
    if kind == "household":
        return {"x": 0.0, "y": 0.0, "z": 0.0}
    angle = (index / max(total, 1)) * math.pi * 2.0 - math.pi / 2.0
    if kind == "member":
        radius = 0.38
        return {
            "x": round(math.cos(angle) * radius, 4),
            "y": round(math.sin(angle) * radius, 4),
            "z": round(_stable_unit(node_id, 0) * 0.14, 4),
        }
    base = member_position or (0.0, 0.0, 0.0)
    radius = 0.30 if kind == "fact" else 0.50 if kind == "memory" else 0.82
    return {
        "x": round(base[0] + math.cos(angle) * radius + _stable_unit(node_id, 0) * 0.08, 4),
        "y": round(base[1] + math.sin(angle) * radius + _stable_unit(node_id, 1) * 0.08, 4),
        "z": round(base[2] + _stable_unit(node_id, 2) * (0.28 if kind != "knowledge" else 0.42), 4),
    }


def build_snapshot(
    session: Session,
    *,
    household: Household,
    actor_id: str,
    allowed_member_ids: set[str],
) -> dict[str, Any]:
    """Build an authorization-filtered family graph for the 3D page."""
    members = list(
        session.scalars(
            select(Member)
            .where(
                Member.household_id == household.id,
                Member.id.in_(allowed_member_ids),
                Member.deleted_at.is_(None),
            )
            .order_by(Member.created_at, Member.id)
        ).all()
    )
    owner_view = household.created_by == actor_id
    now = _now()
    nodes: list[dict[str, Any]] = [
        {
            "id": f"household:{household.id}",
            "kind": "household",
            "category": "household",
            "label": household.name,
            "detail": "家庭数字孪生中心",
            "member_id": None,
            "member_name": None,
            "status": "CONFIRMED",
            "source_kind": "HOUSEHOLD",
            "source_id": household.id,
            "source_recorded_at": household.created_at or now,
            "source_excerpt": None,
            "confidence": 1.0,
            "vector_terms": _vector_terms(_tf(household.name)),
            "vector_size": len(_tf(household.name)),
        }
    ]
    member_positions: dict[str, tuple[float, float, float]] = {}
    fact_nodes: list[dict[str, Any]] = []

    for index, member in enumerate(members):
        member_id_value = f"member:{member.id}"
        position = _projection("member", member_id_value, index, len(members))
        member_positions[member.id] = (position["x"], position["y"], position["z"])
        nodes.append(
            {
                "id": member_id_value,
                "kind": "member",
                "category": "profile",
                "label": member.display_name,
                "detail": f"{member.role} · 成员档案",
                "member_id": member.id,
                "member_name": member.display_name,
                "status": "CONFIRMED",
                "source_kind": "MEMBER",
                "source_id": member.id,
                "source_recorded_at": member.created_at or now,
                "source_excerpt": None,
                "confidence": 1.0,
                "vector_terms": _vector_terms(_tf(f"{member.display_name} {member.role}")),
                "vector_size": len(_tf(f"{member.display_name} {member.role}")),
            }
        )
        from app.projection import build_relationship_graph_view, get_timeline

        for raw in build_relationship_graph_view(get_timeline(session, member.id))["nodes"]:
            category = "medication" if raw["category"] == "drug" else raw["category"]
            vector = _tf(raw["label"])
            fact = {
                "id": f"fact:{raw['id']}",
                "kind": "fact",
                "category": category,
                "label": raw["label"],
                "detail": "来自已确认健康事件",
                "member_id": member.id,
                "member_name": member.display_name,
                "status": "CONFIRMED",
                "source_kind": "HEALTH_EVENT",
                "source_id": raw["source_event_id"],
                "source_recorded_at": raw["source_recorded_at"],
                "source_excerpt": None,
                "confidence": 1.0,
                "vector_terms": _vector_terms(vector),
                "vector_size": len(vector),
                "_vector": vector,
            }
            fact_nodes.append(fact)
            nodes.append(fact)

    memory_stmt = select(DigitalTwinMemory).where(
        DigitalTwinMemory.household_id == household.id,
        DigitalTwinMemory.status != "REJECTED",
    )
    if owner_view:
        memory_stmt = memory_stmt.where(
            DigitalTwinMemory.member_id.in_(allowed_member_ids)
            | DigitalTwinMemory.member_id.is_(None)
        )
    else:
        memory_stmt = memory_stmt.where(DigitalTwinMemory.member_id.in_(allowed_member_ids))
    memories = list(
        session.scalars(memory_stmt.order_by(DigitalTwinMemory.last_seen_at.desc())).all()
    )
    memory_nodes: list[dict[str, Any]] = []
    for memory in memories:
        detail = (
            (memory.attributes or {}).get("detail") if isinstance(memory.attributes, dict) else None
        )
        node = {
            "id": f"memory:{memory.id}",
            "kind": "memory",
            "category": memory.category.casefold(),
            "label": memory.value,
            "detail": detail or memory.label,
            "member_id": memory.member_id,
            "member_name": next(
                (m.display_name for m in members if m.id == memory.member_id), None
            ),
            "status": memory.status,
            "source_kind": memory.source_kind,
            "source_id": memory.id,
            "source_recorded_at": memory.last_seen_at,
            "source_excerpt": memory.evidence_excerpt,
            "confidence": float(memory.confidence or 0.0),
            "vector_terms": _vector_terms(memory.term_vector),
            "vector_size": len(memory.term_vector or {}),
            "_vector": memory.term_vector or {},
        }
        memory_nodes.append(node)
        nodes.append(node)

    knowledge_nodes: list[dict[str, Any]] = []
    docs = list(
        session.scalars(select(KnowledgeDocument).where(KnowledgeDocument.status == "active")).all()
    )
    from app.config import get_settings

    knowledge_admin_ids = get_settings().knowledge_admin_actor_set
    accessible_docs = {
        doc.id: doc
        for doc in docs
        if any(
            _check_permission(
                doc.permission_scope or {},
                actor_id,
                household.id,
                allowed_member_id,
                doc_created_by=doc.created_by,
                knowledge_admin_ids=knowledge_admin_ids,
            )
            for allowed_member_id in (allowed_member_ids or {None})
        )
    }
    if accessible_docs:
        chunks = list(
            session.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.document_id.in_(accessible_docs))
                .order_by(KnowledgeChunk.document_id, KnowledgeChunk.chunk_index)
                .limit(40)
            ).all()
        )
        for chunk in chunks:
            doc = accessible_docs[chunk.document_id]
            vector = chunk.term_vector or {}
            node = {
                "id": f"knowledge:{chunk.id}",
                "kind": "knowledge",
                "category": "knowledge",
                "label": doc.title,
                "detail": f"知识分块 {chunk.chunk_index + 1} · {chunk.locator or '已审核本地资料'}",
                "member_id": None,
                "member_name": None,
                "status": "CONFIRMED",
                "source_kind": "KNOWLEDGE",
                "source_id": chunk.id,
                "source_recorded_at": doc.created_at or now,
                "source_excerpt": chunk.text[:600],
                "confidence": 1.0,
                "vector_terms": _vector_terms(vector),
                "vector_size": len(vector),
                "_vector": vector,
            }
            knowledge_nodes.append(node)
            nodes.append(node)

    for node in nodes:
        if node["kind"] == "household":
            position = _projection("household", node["id"], 0, 1)
        elif node["kind"] == "member":
            position = _projection(
                "member",
                node["id"],
                members.index(next(m for m in members if m.id == node["member_id"])),
                len(members),
            )
        else:
            base = member_positions.get(node["member_id"])
            if node["kind"] == "knowledge":
                base = (0.0, 0.0, 0.0)
            siblings = [
                candidate
                for candidate in nodes
                if candidate["kind"] == node["kind"]
                and candidate.get("member_id") == node.get("member_id")
            ]
            position = _projection(
                node["kind"], node["id"], siblings.index(node), max(len(siblings), 1), base
            )
        node["projection"] = position

    edges: list[dict[str, Any]] = []
    household_node_id = f"household:{household.id}"
    for member in members:
        edges.append(
            {
                "id": f"edge:{household_node_id}:{member.id}",
                "source": household_node_id,
                "target": f"member:{member.id}",
                "relation": "家庭成员",
                "weight": 1.0,
            }
        )
    for node in fact_nodes + memory_nodes:
        if node["member_id"]:
            edges.append(
                {
                    "id": f"edge:member:{node['member_id']}:{node['id']}",
                    "source": f"member:{node['member_id']}",
                    "target": node["id"],
                    "relation": "成员记录",
                    "weight": 1.0,
                }
            )
        else:
            edges.append(
                {
                    "id": f"edge:{household_node_id}:{node['id']}",
                    "source": household_node_id,
                    "target": node["id"],
                    "relation": "家庭记录",
                    "weight": 0.9,
                }
            )

    for memory in memory_nodes:
        related_facts = sorted(
            (
                (_vector_similarity(memory.get("_vector"), fact.get("_vector")), fact)
                for fact in fact_nodes
                if fact["member_id"] == memory["member_id"]
                and fact["category"] == memory["category"]
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        for score, fact in related_facts[:3]:
            if score >= 0.18:
                edges.append(
                    {
                        "id": f"edge:{memory['id']}:{fact['id']}",
                        "source": memory["id"],
                        "target": fact["id"],
                        "relation": "聊天线索 ↔ 已确认事实",
                        "weight": round(score, 4),
                    }
                )

        related_chunks = sorted(
            (
                (_vector_similarity(memory.get("_vector"), chunk.get("_vector")), chunk)
                for chunk in knowledge_nodes
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        for score, chunk in related_chunks[:4]:
            if score >= 0.18:
                edges.append(
                    {
                        "id": f"edge:{memory['id']}:{chunk['id']}",
                        "source": memory["id"],
                        "target": chunk["id"],
                        "relation": "term_vector 关联知识",
                        "weight": round(score, 4),
                    }
                )

    for node in nodes:
        node.pop("_vector", None)

    return {
        "household_id": household.id,
        "generated_at": now,
        "vector_backend": "term_vector",
        "vector_note": (
            "当前展示的是本地词项向量关系投影，不是神经网络语义坐标；连线按词项余弦相似度生成。"
        ),
        "members": [
            {"id": member.id, "display_name": member.display_name, "role": member.role}
            for member in members
        ],
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "member_count": len(members),
            "fact_count": len(fact_nodes),
            "memory_count": len(memory_nodes),
            "unconfirmed_count": sum(1 for node in memory_nodes if node["status"] == "UNCONFIRMED"),
            "knowledge_count": len(knowledge_nodes),
            "edge_count": len(edges),
        },
    }


def promote_memory(
    session: Session,
    *,
    memory: DigitalTwinMemory,
    household: Household,
    actor_id: str,
    correlation_id: str,
) -> str | None:
    """Confirm one memory and, where applicable, append a health event."""
    if memory.status == "CONFIRMED":
        return None
    if memory.status != "UNCONFIRMED":
        raise ValueError("MEMORY_NOT_CONFIRMABLE")
    now = _now()
    event_id: str | None = None
    event_type_by_category = {
        "DISEASE": "disease_added",
        "MEDICATION": "medication_added",
        "ALLERGY": "allergy_added",
        "PLAN": "plan_created",
    }
    event_type = event_type_by_category.get(memory.category)
    if event_type:
        member = session.get(Member, memory.member_id) if memory.member_id else None
        if member is None or member.deleted_at is not None or member.household_id != household.id:
            raise ValueError("MEMORY_MEMBER_INVALID")
        detail = (
            (memory.attributes or {}).get("detail") if isinstance(memory.attributes, dict) else None
        )
        payload: dict[str, Any]
        if memory.category == "DISEASE":
            payload = {"disease": memory.value}
        elif memory.category == "MEDICATION":
            payload = {"drug": memory.value}
            if detail:
                payload["specification"] = detail
        elif memory.category == "ALLERGY":
            payload = {"allergy": memory.value}
        else:
            payload = {"drug": memory.value, "schedule": detail or "未记录"}
        event = append_health_event_transaction(
            session,
            household=household,
            member=member,
            actor_id=actor_id,
            idempotency_key=f"digital-twin:{memory.id}:confirm",
            correlation_id=correlation_id,
            payload=HealthEventCreate(
                member_id=member.id,
                event_type=event_type,
                source="MANUAL",
                confirmation_status="CONFIRMED",
                payload=payload,
                evidence={
                    "source": "digital_twin_chat_memory",
                    "memory_id": memory.id,
                    "evidence_excerpt": memory.evidence_excerpt[:600],
                },
            ),
        )
        event_id = event.id
    memory.status = "CONFIRMED"
    memory.confirmed_by = actor_id
    memory.confirmed_at = now
    memory.updated_at = now
    session.commit()
    return event_id
