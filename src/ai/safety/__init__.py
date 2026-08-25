"""Local safety lexicon and routing helpers for the constrained assistant."""

from ai.safety.lexicon import (
    DATA_EXFILTRATION_TERMS,
    FOLLOW_UP_RISK_TERMS,
    MEDICAL_BOUNDARY_TERMS,
    MEDICATION_SAFETY_ROUTE_TERMS,
    URGENT_ROUTE_TERMS,
    medical_boundary_hits,
)

__all__ = [
    "DATA_EXFILTRATION_TERMS",
    "FOLLOW_UP_RISK_TERMS",
    "MEDICAL_BOUNDARY_TERMS",
    "MEDICATION_SAFETY_ROUTE_TERMS",
    "URGENT_ROUTE_TERMS",
    "medical_boundary_hits",
]
