"""Local synonym / alias expansion for HCT-401 knowledge retrieval.

Kept deliberately tiny and offline: query tokens are expanded before TF-IDF
scoring so colloquial questions still hit teaching cards.  Synonyms never
override permission filtering or citation validation.
"""
from __future__ import annotations

# Each key is a canonical teaching term; values are aliases that should be
# treated as the same retrieval signal.  Expansion is bidirectional.
_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("过期", "过期药", "过期药品", "expired", "expiry", "临期"),
    ("处置", "回收", "丢弃", "take-back", "销毁"),
    ("存放", "储存", "保存", "药箱", "摆放"),
    ("儿童", "小孩", "孩子", "误服", "child"),
    ("过敏", "allergy", "过敏反应"),
    ("授权", "权限", "分享", "可见范围", "字段授权"),
    ("血压", "血糖", "指标", "测量", "趋势"),
    ("急救", "紧急", "120", "急诊", "urgent"),
    ("包装", "药盒", "原包装", "条码", "ocr"),
    ("复核", "人工确认", "人工核对", "review"),
    ("提醒", "再提醒", "未确认", "确认服药", "reminder"),
    ("时间窗", "安全窗", "服药时间", "预算", "告警预算"),
    ("事件", "追加", "不可覆盖", "投影", "纠错"),
    ("规则", "命中", "证据分区", "风险等级"),
    ("本地", "不出网", "隐私", "local-first", "降级"),
    ("拒答", "拒绝", "refuse", "导流", "处方", "开处方", "买药"),
    ("跌倒", "防滑", "环境安全"),
    ("旅行", "外出", "备药", "出行"),
    ("医嘱", "换药", "变更", "计划变更"),
    ("撤权", "删除", "遗忘", "传播", "tombstone"),
    ("天气", "行动卡", "高温", "寒冷"),
    ("盘点", "分类", "清理药箱"),
    ("语音", "朗读", "说话", "speech"),
    ("视觉", "门控", "拍照", "识别", "matched", "conflict"),
    ("剂量", "几片", "吃多少"),  # for refuse-path teaching hits, not advice
)


def _build_lookup() -> dict[str, frozenset[str]]:
    lookup: dict[str, frozenset[str]] = {}
    for group in _SYNONYM_GROUPS:
        normalized = tuple(term.casefold() for term in group if term.strip())
        members = frozenset(normalized)
        for term in normalized:
            lookup[term] = members
    return lookup


_LOOKUP = _build_lookup()


def expand_query_tokens(tokens: list[str]) -> list[str]:
    """Return tokens plus synonym/alias expansions, preserving order.

    Original tokens come first so exact matches still dominate coverage
    weighting; expansions are appended once each.
    """
    expanded: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        key = token.casefold()
        for candidate in (key, *_LOOKUP.get(key, ())):
            if candidate not in seen:
                seen.add(candidate)
                expanded.append(candidate)
    return expanded
