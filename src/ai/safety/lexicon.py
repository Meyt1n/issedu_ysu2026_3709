"""Shared safety / routing lexicon for the local health assistant.

Classification keywords, follow-up sanitizers, and medical-boundary
refusals used to live as three independent lists in ``tool_call.py``.
A missed synonym in one list (but not another) created uneven routing —
for example a colloquial「吃错药了」could fall through to ``GENERAL``
while the same intent expressed as「误服」was blocked.  Keep one source
of truth here; ``tool_call`` imports the shared tuples.
"""

from __future__ import annotations

import re

# Emergency descriptions: route to URGENT and escalate.
URGENT_ROUTE_TERMS: tuple[str, ...] = (
    "呼吸困难",
    "意识异常",
    "疑似中毒",
    "昏迷",
    "抽搐",
    "严重过敏",
)

# Symptom / “what medicine for …” guidance: explain approved knowledge +
# allergy/disease history.  Household formulary is optional enrichment.
SYMPTOM_MEDICATION_INTENT_TERMS: tuple[str, ...] = (
    "吃什么药",
    "用什么药",
    "吃点什么药",
    "该吃什么药",
    "应该吃什么药",
    "可以吃什么药",
    "吃啥药",
    "开什么药",
    "用啥药",
)

SYMPTOM_CONTEXT_TERMS: tuple[str, ...] = (
    "感冒",
    "发烧",
    "发热",
    "咳嗽",
    "头疼",
    "头痛",
    "腹泻",
    "喉咙痛",
    "咽痛",
    "流鼻涕",
    "鼻塞",
    "乏力",
    "不舒服",
    "过敏",
    "皮疹",
)

# High-risk individual medication decisions: stop/switch/interaction/missed
# dose.  These are answerable with reviewed knowledge plus an appended risk
# note (decision 2B), but must never become prescriptions or dose numbers.
MEDICATION_SAFETY_ROUTE_TERMS: tuple[str, ...] = (
    "能不能一起吃",
    "能否一起吃",
    "可以一起吃",
    "能不能同服",
    "能否同服",
    "相互作用",
    "药物相互作用",
    "配伍",
    "停药",
    "换药",
    "怎么服用",
    "同服",
    "剂量",
    "怎么吃",
    "漏服",
    "补服",
    "过量",
    "误服",
    # Colloquial near-synonyms that previously leaked to GENERAL.
    "吃错药",
    "药吃多了",
    "吃多了药",
    "多吃了",
    "少吃了",
    "忘吃药",
    "忘记吃药",
    "拿错药",
    "多吞了",
    "吞多了",
    "吃了两倍",
    "别再吃",
    "可以停用",
    "先停药",
    "能不能停",
    "可以停药",
    "改吃什么",
    "换成别的药",
    "开个处方",
    "开处方",
    "帮我开药",
)

# Negation immediately before a route term must not fire.  News teaching
# prompts say「不开处方」; that is not a request to prescribe.
_NEGATION_PREFIXES = (
    "并不是",
    "不要",
    "不用",
    "并非",
    "不是",
    "未能",
    "没有",
    "别",
    "未",
    "勿",
    "非",
    "没",
    "不",
)


def contains_lexicon_term(text: str, term: str) -> bool:
    """True when *term* occurs in *text* without a leading negation."""
    if not term:
        return False
    start = 0
    haystack = str(text or "")
    while True:
        index = haystack.find(term, start)
        if index < 0:
            return False
        prefix = haystack[:index]
        if any(prefix.endswith(negation) for negation in _NEGATION_PREFIXES):
            start = index + 1
            continue
        return True


def contains_any_lexicon_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(contains_lexicon_term(text, term) for term in terms)

# Decision 1A: explicit individual dose-number requests are the only hard
# refusal subset.  A question that asks "how many pills / how much" for a
# person is answered with a deterministic refusal — never with a number —
# regardless of evidence, mode, or environment (8C).
DOSE_DECISION_ROUTE_TERMS: tuple[str, ...] = (
    "一次吃多少",
    "一次吃几",
    "一天吃几",
    "一天吃多少",
    "每次吃几",
    "每次吃多少",
    "每天吃几",
    "每天吃多少",
    "吃几粒",
    "吃几片",
    "服几粒",
    "服几片",
    "剂量是多少",
    "剂量多少",
    "用量是多少",
    "用量多少",
    "剂量改成",
    "剂量调成",
    "调整剂量",
    "调整一下剂量",
    "加大剂量",
    "减少剂量",
    "剂量加倍",
    "双倍剂量",
    "补双倍",
    "吃双倍",
    "加倍吃",
)

# Bare quantity asks（“布洛芬吃多少”）hard-refuse only with drug context so
# that lifestyle questions（“吃多少盐合适”）are not refused.
_DOSE_BARE_QUANTITY_TERMS: tuple[str, ...] = (
    "吃多少",
    "该吃多少",
    "应该吃多少",
    "服多少",
    "服用多少",
    "用多少",
)
_DRUG_CONTEXT_RE = re.compile(
    r"药|胶囊|冲剂|口服液|糖浆|滴剂|栓剂|喷雾|贴剂|注射|"
    r"布洛芬|阿莫西林|对乙酰氨基酚|扑热息痛|阿司匹林|头孢|青霉素|"
    r"退烧|止咳|消炎|抗生素|降压|降糖|"
    r"粒|片剂|丸|毫克|毫升|mg|ml"
)

# 「一天几粒 / 每次几片」without an explicit 吃/服 verb previously leaked to
# GENERAL.  The pattern pairs a serving-frequency prefix with an asked
# quantity + pill unit; concrete numbers (误服了两粒) stay MEDICATION_SAFETY.
_DOSE_QUANTITY_ASK_RE = re.compile(
    r"(?:一次|每次|一天|每天|每日|一顿|一回|饭前|饭后|睡前)"
    r"[^。！？!?\n]{0,6}?(?:几|多少)\s*"
    r"(?:粒|片|颗|丸|毫克|毫升|mg|ml|克|袋|支|滴|次)"
)
# Stock-taking questions（家里还剩几粒药）are inventory, not dose decisions.
_DOSE_INVENTORY_GUARD_RE = re.compile(
    r"(?:剩|余|还有|库存|存货|囤|买)[^。！？!?\n]{0,4}(?:几|多少)"
)


def is_dose_decision_query(text: str) -> bool:
    """True when the question asks for a concrete individual dose number."""
    normalized = re.sub(r"\s+", "", str(text or "").casefold())
    if not normalized:
        return False
    if _DOSE_INVENTORY_GUARD_RE.search(normalized):
        return False
    if any(term in normalized for term in DOSE_DECISION_ROUTE_TERMS):
        return True
    if any(term in normalized for term in _DOSE_BARE_QUANTITY_TERMS) and _DRUG_CONTEXT_RE.search(
        normalized
    ):
        return True
    return bool(_DOSE_QUANTITY_ASK_RE.search(normalized))

# Follow-up prompts must not invite a concrete individual dose number.
# Stop / switch / interaction topics are answerable teaching content now, so
# they no longer force the generic "let a doctor confirm" follow-up ladder.
FOLLOW_UP_RISK_TERMS: tuple[str, ...] = (
    DOSE_DECISION_ROUTE_TERMS
    + _DOSE_BARE_QUANTITY_TERMS
    + (
        "几粒",
        "几片",
    )
)

# Narrowed scope (2026-08 relaxation): the assistant may now explain general
# medical knowledge — mechanisms, what a symptom usually means, when to see a
# doctor, why two drugs interact — in ordinary language.  Only two things stay
# out of bounds because they impersonate a clinician or monetise the chat:
# writing an actual prescription block, and commercial / referral solicitation.
# Individual dose numbers are handled separately by the dose rules below, which
# remain the one hard limit.
#
# Still enforced by ``sanitize_answer_sentences`` — but note what is no longer
# here: 诊断 / 确诊 / 给药 / 建议停药 / 建议换药 / 你必须 …  Those made ordinary
# explanation unpublishable and are gone.
MEDICAL_BOUNDARY_TERMS: tuple[str, ...] = (
    "处方:",
    "处方：",
    "Prescription:",
    "点击购买",
    "立即下单",
    "购买链接",
    "加我微信",
    "添加微信",
    "咨询电话",
)

DATA_EXFILTRATION_TERMS: tuple[str, ...] = (
    "身份证号",
    "身份证号码",
    "联系方式",
    "手机号码",
    "银行卡号",
)

# Kept short on purpose: a long boilerplate block appended to every answer made
# the assistant read like a disclaimer generator rather than a helper.
TEACHING_REMINDER = "（具体用药和剂量请以说明书或医生、药师的意见为准。）"

# A refusal or safety disclaimer is not itself a prohibited medical directive.
# Check the short phrase immediately before a matched noun so text such as
# “不诊断、不开处方” remains answerable while “建议开处方” is blocked.
_MEDICAL_NEGATION_PREFIXES: tuple[str, ...] = (
    "不",
    "不要",
    "无需",
    "不用",
    "禁止",
    "请勿",
    "不能",
    "无法",
    "不得",
    "避免",
    "不提供",
    "不建议",
    "不构成",
    "不开",
    "不要开",
    "不能开",
    "不得开",
)


def _is_negated_medical_term(text: str, start: int) -> bool:
    prefix = text[max(0, start - 24):start]
    return any(prefix.endswith(marker) for marker in _MEDICAL_NEGATION_PREFIXES) or any(
        marker in prefix for marker in ("不能替代", "不可作为", "不应作为", "不构成")
    )


def medical_boundary_hits(text: str) -> list[str]:
    """Return boundary terms that appear in ``text`` (case-insensitive for Latin)."""
    if not text:
        return []
    lowered = text.casefold()
    hits: list[str] = []
    for term in MEDICAL_BOUNDARY_TERMS:
        needle = term.casefold()
        if needle not in lowered and term not in text:
            continue
        start = lowered.find(needle)
        if start >= 0 and _is_negated_medical_term(text, start):
            continue
        if term in text and _is_negated_medical_term(text, text.find(term)):
            continue
        if needle in lowered or term in text:
            hits.append(term)
    return hits


# ── Output-side sentence sanitisation (decision 1A + blacklist softening) ──

# Concrete per-serving dose numbers in model output（每次2片 / 一天三粒）。
# This is now the only rule that deletes a sentence, so it must not fire on
# ordinary lifestyle advice.  Pill-shaped units are unambiguous; volume and
# package units（毫升 / 袋 / 滴）only count as a dose when the same sentence
# actually talks about medicine, otherwise「每天喝2袋牛奶」would be censored.
_DOSE_SERVING_PREFIX = (
    r"(?:每次|一次|每天|一天|每日|每晚|每早|每隔\S{1,4}|一顿|饭前|饭后|睡前)"
    r"[^。！？!?\n]{0,8}?"
    r"(?:\d+(?:\.\d+)?|[一二两三四五六七八九十半])\s*"
)
_OUTPUT_DOSE_DIRECTIVE_RE = re.compile(_DOSE_SERVING_PREFIX + r"(?:粒|片|颗|丸|毫克|mg)")
_OUTPUT_DOSE_AMBIGUOUS_RE = re.compile(_DOSE_SERVING_PREFIX + r"(?:毫升|ml|支|袋|滴)")

# Real medicine mentions only — deliberately excludes measurement units, so
# that「每天喝500毫升水」is not treated as a drug sentence by its unit alone.
_MEDICINE_MENTION_RE = re.compile(
    r"药|胶囊|冲剂|口服液|糖浆|滴剂|栓剂|喷雾|贴剂|注射|输液|"
    r"布洛芬|阿莫西林|对乙酰氨基酚|扑热息痛|阿司匹林|头孢|青霉素|蒙脱石|奥美拉唑|"
    r"退烧|退热|止咳|消炎|抗生素|抗菌|降压|降糖|镇痛|服用|口服"
)

_EXTERNAL_LINK_RE = re.compile(r"https?://[^\s<\"']+", re.IGNORECASE)

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？!?；;\n])")

SANITIZED_FOOTNOTE = "（涉及具体服用数量的那句已略去，请以说明书或医生、药师的意见为准。）"
_SANITIZED_FOOTNOTE_OTHER = "（个别涉及外部链接或推广内容的语句已略去。）"


def output_dose_directive_hits(text: str) -> list[str]:
    """Return concrete individual dose-number directives found in ``text``.

    Pill-shaped units always count.  Volume / package units count only when the
    surrounding text mentions medicine, so nutrition and hydration advice such
    as「每天喝2袋牛奶」is left alone.
    """
    if not text:
        return []
    hits = [match.group(0) for match in _OUTPUT_DOSE_DIRECTIVE_RE.finditer(text)]
    if _MEDICINE_MENTION_RE.search(text):
        hits += [match.group(0) for match in _OUTPUT_DOSE_AMBIGUOUS_RE.finditer(text)]
    return hits


def split_sentences(text: str) -> list[str]:
    """Split on Chinese/Latin sentence enders, keeping the delimiters."""
    return [part for part in _SENTENCE_BOUNDARY_RE.split(str(text or "")) if part]


def sanitize_answer_sentences(text: str) -> tuple[str, list[str]]:
    """Remove the few sentence kinds the assistant must never deliver.

    Returns ``(cleaned_text, removal_reasons)`` with reasons drawn from
    {"DOSE_NUMBER", "MEDICAL_BOUNDARY", "EXTERNAL_LINK"}.

    Medical *explanation* is no longer filtered: what a symptom usually means,
    why two drugs interact, why not to stop an antibiotic early, when to see a
    doctor — all of that is ordinary teaching content and passes through.  What
    still goes is narrow and deliberate:

    * ``DOSE_NUMBER`` — a concrete individual dose quantity（每次两片）。This is
      the one hard medical limit.
    * ``MEDICAL_BOUNDARY`` — a written-out prescription block, or commercial
      solicitation（点击购买 / 加我微信）。Not a medical-content rule: it keeps the
      assistant from becoming an ad or referral channel.
    * ``EXTERNAL_LINK`` — bare URLs, the usual carrier for the above.

    When nothing survives, the caller falls back to a structured degrade
    response.
    """
    reasons: list[str] = []
    kept: list[str] = []
    for sentence in split_sentences(text):
        if not sentence.strip():
            continue
        if output_dose_directive_hits(sentence):
            reasons.append("DOSE_NUMBER")
            continue
        if medical_boundary_hits(sentence):
            reasons.append("MEDICAL_BOUNDARY")
            continue
        if _EXTERNAL_LINK_RE.search(sentence):
            reasons.append("EXTERNAL_LINK")
            continue
        kept.append(sentence)
    cleaned = "".join(kept).strip()
    if reasons and cleaned:
        footnote = (
            SANITIZED_FOOTNOTE
            if "DOSE_NUMBER" in reasons
            else _SANITIZED_FOOTNOTE_OTHER
        )
        cleaned = f"{cleaned}\n\n{footnote}"
    return cleaned, reasons
