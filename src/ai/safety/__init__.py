"""Local safety lexicon and routing helpers for the constrained assistant."""

from ai.safety.classifier import (
    classify_question_dual,
    classify_question_lexicon,
    merge_query_types,
    parse_model_query_type,
)
from ai.safety.lexicon import (
    DATA_EXFILTRATION_TERMS,
    FOLLOW_UP_RISK_TERMS,
    MEDICAL_BOUNDARY_TERMS,
    MEDICATION_SAFETY_ROUTE_TERMS,
    SYMPTOM_CONTEXT_TERMS,
    SYMPTOM_MEDICATION_INTENT_TERMS,
    TEACHING_REMINDER,
    URGENT_ROUTE_TERMS,
    medical_boundary_hits,
)

__all__ = [
    "DATA_EXFILTRATION_TERMS",
    "FOLLOW_UP_RISK_TERMS",
    "MEDICAL_BOUNDARY_TERMS",
    "MEDICATION_SAFETY_ROUTE_TERMS",
    "SYMPTOM_CONTEXT_TERMS",
    "SYMPTOM_MEDICATION_INTENT_TERMS",
    "TEACHING_REMINDER",
    "URGENT_ROUTE_TERMS",
    "classify_question_dual",
    "classify_question_lexicon",
    "medical_boundary_hits",
    "merge_query_types",
    "parse_model_query_type",
]
