"""StakeholderReqsNode — identifies stakeholder groups and communication requirements."""

# Inner Cat 2 domain node — must use TrustLevel.ANONYMOUS (trust verified at boundary).
# Presents requirements as briefing support only.
# Does NOT send notifications, publish announcements, or commit a schedule.

from __future__ import annotations

from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.schemas.state import from_json, to_json

# Stakeholder group definitions — maps change_type to likely affected groups
_CHANGE_TYPE_STAKEHOLDER_MAP: dict[str, list[dict]] = {
    "postponement": [
        {
            "group_name": "Participants",
            "requirement_summary": (
                "Notify all registered participants of rescheduled date/time. "
                "Reference participation agreements for required notification windows."
            ),
            "cited_source": "participant_registry",
            "missing_flag": False,
        },
        {
            "group_name": "Ticketholders",
            "requirement_summary": (
                "Issue ticketholder notification per ticketing terms. "
                "Assess refund-eligibility obligations for date-change scenarios."
            ),
            "cited_source": "ticketing_system",
            "missing_flag": False,
        },
        {
            "group_name": "Broadcast Partners",
            "requirement_summary": (
                "Alert broadcast rights-holders per contractual notice provisions. "
                "Confirm revised schedule and check coverage-window implications."
            ),
            "cited_source": "broadcast_rights_register",
            "missing_flag": False,
        },
        {
            "group_name": "Sponsors",
            "requirement_summary": (
                "Advise sponsors per sponsorship-agreement notification clauses. "
                "Assess exposure-commitment impacts and force-majeure applicability."
            ),
            "cited_source": "sponsor_register",
            "missing_flag": False,
        },
    ],
    "cancellation": [
        {
            "group_name": "Participants",
            "requirement_summary": (
                "Issue cancellation notice per participant agreements. " "Identify refund or compensation obligations."
            ),
            "cited_source": "participant_registry",
            "missing_flag": False,
        },
        {
            "group_name": "Ticketholders",
            "requirement_summary": ("Issue full-cancellation notice; trigger refund process per ticketing terms."),
            "cited_source": "ticketing_system",
            "missing_flag": False,
        },
        {
            "group_name": "Broadcast Partners",
            "requirement_summary": ("Notify broadcast rights-holders of cancellation; assess liability provisions."),
            "cited_source": "broadcast_rights_register",
            "missing_flag": False,
        },
        {
            "group_name": "Insurance Provider",
            "requirement_summary": (
                "File cancellation notice with insurer per policy terms. "
                "Initiate claims assessment process where applicable."
            ),
            "cited_source": "insurance_policy_register",
            "missing_flag": False,
        },
    ],
    "venue_change": [
        {
            "group_name": "Participants",
            "requirement_summary": ("Notify participants of revised venue details per participation agreements."),
            "cited_source": "participant_registry",
            "missing_flag": False,
        },
        {
            "group_name": "Ticketholders",
            "requirement_summary": (
                "Issue venue-change notification; confirm validity of existing tickets at new venue."
            ),
            "cited_source": "ticketing_system",
            "missing_flag": False,
        },
        {
            "group_name": "Venue Operator",
            "requirement_summary": (
                "Formalise venue-change agreement amendments. " "Confirm infrastructure obligations at new venue."
            ),
            "cited_source": "venue_agreement_register",
            "missing_flag": False,
        },
    ],
}

# Default stakeholder groups when change type is not specifically mapped
_DEFAULT_STAKEHOLDER_GROUPS: list[dict] = [
    {
        "group_name": "Participants",
        "requirement_summary": (
            "Review participation agreements for notification obligations applicable to this change."
        ),
        "cited_source": "participant_registry",
        "missing_flag": False,
    },
    {
        "group_name": "Relevant Counterparties",
        "requirement_summary": ("Review all active agreements for notice requirements applicable to schedule changes."),
        "cited_source": None,
        "missing_flag": True,
    },
]


class StakeholderReqsNode(FunctionNode):
    """Identify stakeholder groups and communication requirements for the schedule change.

    - Identifies groups from configured approved sources and documented change context
    - Presents requirements as briefing support only — does not initiate communications
    - Marks missing or unverifiable requirements explicitly
    - Retains cited provenance for all identified requirements
    """

    # Inner domain node — trust already verified at PreProcessNode boundary
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict) -> dict:
        """Identify stakeholder groups and communication requirements."""
        _ic = state.get("input_context") or {}
        change_scope = from_json(state.get("change_scope_json") or _ic.get("change_scope_json"), default={})
        approved_sources = from_json(state.get("approved_sources_json") or _ic.get("approved_sources_json"), default=[])

        change_type = change_scope.get("change_type", "unknown")

        # Use change-type-specific mappings where available
        stakeholder_reqs = _CHANGE_TYPE_STAKEHOLDER_MAP.get(change_type, [])

        # If no specific mapping, use defaults with missing-data flags
        if not stakeholder_reqs:
            stakeholder_reqs = list(_DEFAULT_STAKEHOLDER_GROUPS)

        # Flag any group whose cited_source is not in the approved_sources list
        for req in stakeholder_reqs:
            cited = req.get("cited_source")
            if cited and approved_sources and cited not in approved_sources:
                req = dict(req)
                req["missing_flag"] = True
                req["requirement_summary"] = f"[UNVERIFIED SOURCE] {req['requirement_summary']}"

        emit_trace_event(
            "StakeholderReqsNode_requirements_identified",
            {
                "change_type": change_type,
                "stakeholder_group_count": len(stakeholder_reqs),
                "groups_with_missing_data": sum(1 for r in stakeholder_reqs if r.get("missing_flag")),
            },
            state,
        )

        return {
            "stakeholder_reqs_json": to_json(stakeholder_reqs),
            "status": AgentStatus.SUCCESS.value,
        }
