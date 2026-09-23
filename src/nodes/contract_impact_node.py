"""ContractImpactNode — maps schedule-change evidence to approved contractual-impact references."""

# Inner Cat 2 domain node — must use TrustLevel.ANONYMOUS (trust verified at boundary).
# Produces traceable evidence and uncertainty markers — NOT legal advice.
# Does not modify contracts, approve schedule changes, or make binding determinations.

from __future__ import annotations

from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.schemas.state import from_json, to_json

# Approved contractual-impact reference categories — limits scope to known types
_IMPACT_CATEGORIES = frozenset(
    {
        "broadcast_rights",
        "venue_agreement",
        "participant_obligation",
        "sponsor_agreement",
        "ticketing_obligation",
        "insurance_clause",
        "force_majeure",
        "notification_obligation",
    }
)

# Keyword mappings from change type to likely impact categories (reference only)
_CHANGE_TYPE_TO_IMPACT_HINTS: dict[str, list[str]] = {
    "postponement": ["notification_obligation", "ticketing_obligation", "broadcast_rights"],
    "cancellation": ["force_majeure", "insurance_clause", "refund_obligation"],
    "venue_change": ["venue_agreement", "ticketing_obligation", "broadcast_rights"],
    "time_change": ["broadcast_rights", "participant_obligation", "notification_obligation"],
    "format_change": ["participant_obligation", "sponsor_agreement", "broadcast_rights"],
    "division_change": ["participant_obligation", "venue_agreement"],
}


class ContractImpactNode(FunctionNode):
    """Map normalized schedule-change evidence to approved contractual-impact references.

    Output is traceable decision support only:
    - Returns referenced clause categories and stated obligation summaries
    - Marks uncertainty when evidence is insufficient
    - Returns safe partial results when reference evidence is unavailable
    - Does NOT provide legal advice, approve changes, or modify contracts
    """

    # Inner domain node — trust already verified at PreProcessNode boundary
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict) -> dict:
        """Analyse schedule-history evidence and identify contractual-impact references."""
        _ic = state.get("input_context") or {}
        change_scope = from_json(state.get("change_scope_json") or _ic.get("change_scope_json"), default={})
        history_records = from_json(state.get("schedule_history_json"), default=[])

        change_type = change_scope.get("change_type", "unknown")

        # Identify relevant impact category hints based on change type
        hint_categories = _CHANGE_TYPE_TO_IMPACT_HINTS.get(change_type, [])

        contract_impacts: list[dict] = []

        if not history_records:
            # No evidence available — return placeholder with uncertainty flag
            contract_impacts = [
                {
                    "clause_ref": "UNKNOWN",
                    "summary": "No schedule-change history evidence available for impact mapping.",
                    "obligation_type": "unclassified",
                    "uncertainty_flag": True,
                    "evidence_source": None,
                }
            ]
            emit_trace_event(
                "ContractImpactNode_no_evidence",
                {
                    "change_type": change_type,
                    "impact_count": 0,
                    "uncertainty": True,
                },
                state,
            )
            return {
                "contract_impacts_json": to_json(contract_impacts),
                "status": AgentStatus.SUCCESS.value,
            }

        # Build impact references from available evidence and hint categories
        referenced_categories: set[str] = set()
        for record in history_records:
            desc = str(record.get("description", "")).lower()
            record_change_type = str(record.get("change_type", "")).lower()
            for category in hint_categories:
                # Match based on keyword presence in description or change_type
                if category.replace("_", " ") in desc or record_change_type in category:
                    referenced_categories.add(category)

        # If no categories matched from evidence, mark as uncertain
        if not referenced_categories:
            referenced_categories = set(hint_categories[:2]) if hint_categories else {"unclassified"}
            uncertainty = True
        else:
            uncertainty = False

        # Build one reference entry per identified category
        for category in sorted(referenced_categories):
            if category not in _IMPACT_CATEGORIES:
                continue
            impact = {
                "clause_ref": category.upper(),
                "summary": _build_impact_summary(category, change_type),
                "obligation_type": category,
                "uncertainty_flag": uncertainty,
                "evidence_source": [r.get("record_id") for r in history_records[:3]],
            }
            contract_impacts.append(impact)

        emit_trace_event(
            "ContractImpactNode_mapping_complete",
            {
                "change_type": change_type,
                "impact_count": len(contract_impacts),
                "uncertainty": uncertainty,
                "categories_identified": sorted(referenced_categories),
            },
            state,
        )

        return {
            "contract_impacts_json": to_json(contract_impacts),
            "status": AgentStatus.SUCCESS.value,
        }


def _build_impact_summary(category: str, change_type: str) -> str:
    """Build a descriptive summary string for a contractual-impact reference.

    This is decision-support text only — not legal advice.
    """
    summaries = {
        "broadcast_rights": (
            f"A {change_type} may trigger review of broadcast-rights clauses "
            "regarding scheduling commitments and notification obligations."
        ),
        "venue_agreement": (
            f"A {change_type} may affect venue-agreement terms including "
            "availability windows and infrastructure obligations."
        ),
        "participant_obligation": (
            f"A {change_type} may implicate participant agreements including "
            "participation requirements and scheduling commitments."
        ),
        "sponsor_agreement": (
            f"A {change_type} may affect sponsor-agreement terms regarding "
            "event delivery, exposure rights, and force majeure provisions."
        ),
        "ticketing_obligation": (
            f"A {change_type} may require review of ticketing terms including "
            "refund obligations and date-change notification requirements."
        ),
        "insurance_clause": (
            f"A {change_type} may trigger insurance policy review for "
            "cancellation coverage and liability provisions."
        ),
        "force_majeure": (
            f"A {change_type} may invoke force majeure provisions — "
            "legal review is recommended before relying on this clause."
        ),
        "notification_obligation": (
            f"A {change_type} likely triggers contractual notification obligations "
            "to counterparties within specified timeframes."
        ),
    }
    return summaries.get(
        category,
        f"A {change_type} may have implications for {category.replace('_', ' ')} clauses — review recommended.",
    )
