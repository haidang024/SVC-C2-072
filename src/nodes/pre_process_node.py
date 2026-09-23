"""PreProcessNode — validates and normalizes schedule-change scope and approved-source identifiers."""

# Node contract:
#  - Extend FunctionNode; implement execute(state) -> dict
#  - Return ONLY the fields this node changes (never full state)
#  - Return AgentStatus.<X>.value strings for status assignments
#  - Read input_context via state.get("input_context", {}) — read-only
#  - Never import from mediator/, api/, or other agents
#  - Outer Cat 2 node → required_trust_level = VERIFIED_EXTERNAL

from __future__ import annotations

import re
from typing import Any, ClassVar

from framework.errors import SecurityViolationError
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.schemas.state import to_json

# Allowed change type values — restricts scope to known operational categories
_ALLOWED_CHANGE_TYPES = frozenset(
    {
        "postponement",
        "cancellation",
        "venue_change",
        "time_change",
        "format_change",
        "division_change",
    }
)

# Maximum number of approved sources per request — prevents unbounded retrieval
_MAX_APPROVED_SOURCES = 10

# Maximum length for free-text criteria field
_MAX_CRITERIA_LENGTH = 2048
_GREETING_ONLY = re.compile(r"^(?:hello|hi|hey|hello[,. ]*hi|xin chào|chào|こんにちは)[!. ,]*$", re.IGNORECASE)
_INPUT_GUIDANCE = [
    "Provide event_id or competition_name in input_context.",
    "Set change_type to postponement, cancellation, venue_change, time_change, format_change, or division_change.",
    "Optionally provide effective_window, change_criteria, requester_id, and approved_sources.",
]


def _input_error(message: str) -> dict[str, Any]:
    return {
        "status": AgentStatus.SUCCESS.value,
        "validated_input": "",
        "input_error_message": message,
        "input_error_guidance": "\n".join(_INPUT_GUIDANCE),
    }


class PreProcessNode(FunctionNode):
    """Outer Cat 2 pre-process node — validates change scope and approved-source identifiers.

    Enforces:
    - Presence and format of event_id / competition_name
    - change_type belongs to the allowed operational set
    - approved_sources list is bounded and each entry is a non-empty string
    - No credentials or restricted data in input payloads
    """

    # S-1: outer boundary node — requires verified external caller
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def _extra_security_gate_input(self, state: dict) -> dict:
        """S-2 domain extension: enforce change-scope structure and source allowlist bounds.

        Runs after the default PII scan. Raises SecurityViolationError on domain violations.
        Must return state on the non-error path.
        """
        user_input = state.get("user_input", "")
        if not user_input or not str(user_input).strip():
            return {**state, **_input_error("No schedule-change briefing request was provided.")}

        input_context = state.get("input_context", {}) or {}
        change_type = input_context.get("change_type", "")
        if change_type and change_type not in _ALLOWED_CHANGE_TYPES:
            return {**state, **_input_error(f"change_type '{change_type}' is not in the supported set.")}

        sources = input_context.get("approved_sources", []) or []
        if len(sources) > _MAX_APPROVED_SOURCES:
            raise SecurityViolationError(f"PreProcessNode: approved_sources exceeds maximum of {_MAX_APPROVED_SOURCES}")

        criteria = input_context.get("change_criteria", "") or ""
        if len(str(criteria)) > _MAX_CRITERIA_LENGTH:
            raise SecurityViolationError(
                f"PreProcessNode: change_criteria exceeds maximum length of {_MAX_CRITERIA_LENGTH}"
            )

        return state

    def execute(self, state: dict) -> dict:
        """Validate and normalize the schedule-change request scope."""
        user_input = state.get("user_input", "")
        input_context = state.get("input_context", {}) or {}

        if not user_input or not str(user_input).strip():
            emit_trace_event(
                "PreProcessNode_validation_failed",
                {"reason": "empty_user_input"},
                state,
            )
            return _input_error("No schedule-change briefing request was provided.")

        # Normalise change scope from input_context (structured request fields)
        event_id = str(input_context.get("event_id", "")).strip()
        competition_name = str(input_context.get("competition_name", "")).strip()
        change_type = str(input_context.get("change_type", "unknown")).strip()
        effective_window = str(input_context.get("effective_window", "")).strip()
        change_criteria = str(input_context.get("change_criteria", str(user_input).strip())).strip()
        requester_id = str(input_context.get("requester_id", "")).strip()

        if change_type not in _ALLOWED_CHANGE_TYPES:
            return _input_error(f"change_type '{change_type}' is not in the supported set.")

        # Require at minimum a competition name or event identifier
        if not event_id and not competition_name:
            emit_trace_event(
                "PreProcessNode_validation_failed",
                {"reason": "missing_event_or_competition"},
                state,
            )
            if _GREETING_ONLY.fullmatch(str(user_input).strip()):
                return _input_error("The message contains only a greeting and no schedule-change request.")
            return _input_error("At least one of event_id or competition_name must be provided.")

        change_scope = {
            "event_id": event_id,
            "competition_name": competition_name,
            "change_type": change_type if change_type in _ALLOWED_CHANGE_TYPES else "unknown",
            "effective_window": effective_window,
            "change_criteria": change_criteria,
            "requester_id": requester_id,
        }

        # Normalise and bound approved_sources list
        raw_sources = input_context.get("approved_sources", []) or []
        approved_sources = [str(s).strip() for s in raw_sources if s and str(s).strip()][:_MAX_APPROVED_SOURCES]

        emit_trace_event(
            "PreProcessNode_scope_validated",
            {
                "event_id": event_id,
                "competition_name": competition_name,
                "change_type": change_scope["change_type"],
                "approved_source_count": len(approved_sources),
                # Do not log change_criteria — may contain operator-internal detail
            },
            state,
        )

        # Propagate hitl_allowed from input_context into state so inner nodes respect it
        # (operator can suppress HITL for testing/STG by setting hitl_allowed: false in input_context)
        hitl_override = input_context.get("hitl_allowed")
        result: dict = {
            "validated_input": change_criteria,
            "change_scope_json": to_json(change_scope),
            "approved_sources_json": to_json(approved_sources),
            "enriched_context": {
                "source": "svc-c2-072",
                "channel": input_context.get("channel", "unknown"),
            },
            "status": AgentStatus.SUCCESS.value,
        }
        if hitl_override is not None:
            result["hitl_allowed"] = bool(hitl_override)
        return result
