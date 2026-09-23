"""PostProcessNode — formats the final traceable stakeholder briefing output."""

# Outer Cat 2 post-process node — required_trust_level = VERIFIED_EXTERNAL.
# Retains verifiable provenance without exposing credentials or raw restricted source payloads.
# Uses _extra_security_gate_output() for domain-specific output validation.

from __future__ import annotations

from typing import ClassVar

from framework.errors import SecurityViolationError
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.schemas.state import from_json, to_json
from src.services.llm_runtime import provider_metadata, request_advisory

# Maximum allowed length for formatted_output to prevent runaway responses
_MAX_OUTPUT_LENGTH = 50_000


class PostProcessNode(FunctionNode):
    """Outer post-process node — builds the final formatted briefing response.

    Assembles the human-reviewed briefing (or cancellation notice), attaches provenance
    metadata, and enforces output safety checks.

    Output is decision support ONLY — does not approve schedule changes, send notifications,
    modify contracts, or make operational commitments.
    """

    # S-1: outer boundary node — requires verified external caller
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm: object | None = None, config: dict | None = None) -> None:
        super().__init__()
        self._llm = llm
        self._config = config or {}

    def _extra_security_gate_output(self, result: dict) -> dict:
        """S-3 domain extension: ensure formatted_output does not exceed safe bounds.

        Must return result on the non-error path.
        """
        output = result.get("formatted_output", "")
        if isinstance(output, str) and len(output) > _MAX_OUTPUT_LENGTH:
            raise SecurityViolationError(
                f"PostProcessNode: formatted_output exceeds maximum length of {_MAX_OUTPUT_LENGTH}"
            )
        return result

    def execute(self, state: dict) -> dict:
        """Build the final formatted output including briefing, provenance, and limitations."""
        if state.get("input_error_message"):
            message = str(state["input_error_message"])
            return {"formatted_output": message, "status": AgentStatus.SUCCESS.value, "input_error_message": message}
        request_advisory(
            state,
            "Review the safety of a deterministic schedule-change briefing.",
            self._llm,
            timeout_s=float(self._config.get("timeout_s", 30)),
            max_retry=int(self._config.get("max_retry", 3)),
        )
        briefing_draft = state.get("briefing_draft", "")
        citations = from_json(state.get("citations_json"), default=[])
        contract_impacts = from_json(state.get("contract_impacts_json"), default=[])
        stakeholder_reqs = from_json(state.get("stakeholder_reqs_json"), default=[])
        retrieval_errors = from_json(state.get("retrieval_errors_json"), default=[])
        review_outcome = state.get("review_outcome", "")
        review_notes = state.get("review_notes", "")
        partial_result = state.get("partial_result", False)
        change_scope = from_json(state.get("change_scope_json"), default={})

        # Handle rejection outcome — return safe cancellation notice
        if review_outcome == "rejected":
            emit_trace_event(
                "PostProcessNode_briefing_rejected",
                {"review_outcome": "rejected"},
                state,
            )
            formatted = (
                "# Stakeholder Briefing — Review Rejected\n\n"
                "The stakeholder briefing draft was rejected during human review. "
                "No stakeholder briefing is released.\n\n"
                f"**Review notes:** {review_notes or 'None provided.'}\n\n"
                "> This output is decision support only. No schedule change has been approved "
                "and no stakeholders have been notified."
            )
            return {
                "formatted_output": formatted,
                "result": to_json(
                    {
                        "status": "rejected",
                        "review_outcome": "rejected",
                        "review_notes": review_notes,
                        "message": "Briefing rejected during human review. No output released.",
                    }
                ),
                "status": AgentStatus.SUCCESS.value,
                **provider_metadata(state),
            }

        if not briefing_draft:
            emit_trace_event(
                "PostProcessNode_no_briefing_draft",
                {"review_outcome": review_outcome},
                state,
            )
            formatted = (
                "# Stakeholder Briefing — No Output Available\n\n"
                "The briefing agent was unable to produce a complete stakeholder briefing "
                "from the available approved sources.\n\n"
            )
            if retrieval_errors:
                formatted += "**Data Retrieval Issues:**\n"
                for err in retrieval_errors:
                    formatted += f"- {err}\n"
            formatted += (
                "\n> This output is decision support only. No schedule change has been "
                "approved and no stakeholders have been notified."
            )
            return {
                "formatted_output": formatted,
                "result": to_json(
                    {
                        "status": "partial",
                        "review_outcome": review_outcome,
                        "message": "Incomplete briefing — see retrieval issues.",
                        "retrieval_errors": retrieval_errors,
                    }
                ),
                "status": AgentStatus.SUCCESS.value,
                **provider_metadata(state),
            }

        # Build final formatted output with provenance metadata footer
        result_payload: dict = {
            "status": "success",
            "review_outcome": review_outcome,
            "review_notes": review_notes if review_notes else None,
            "partial_data": partial_result,
            "change_scope": {
                "event_id": change_scope.get("event_id", ""),
                "competition_name": change_scope.get("competition_name", ""),
                "change_type": change_scope.get("change_type", ""),
            },
            "impact_summary": {
                "contractual_references_count": len(contract_impacts),
                "stakeholder_groups_count": len(stakeholder_reqs),
                "citations_count": len(citations),
            },
            "limitations": [
                "Output is produced from operator-configured approved sources only.",
                "Does not constitute legal advice, schedule approval, or any operational commitment.",
                "Human review and expert consultation required before any action.",
            ],
        }

        if partial_result and retrieval_errors:
            result_payload["retrieval_errors"] = retrieval_errors

        if review_outcome == "corrected" and review_notes:
            result_payload["human_correction_applied"] = True

        # Compose final formatted output: briefing + metadata footer
        metadata_footer = (
            "\n\n---\n"
            "**Briefing Metadata:**\n"
            f"- Review outcome: {review_outcome}\n"
            f"- Contractual references identified: {len(contract_impacts)}\n"
            f"- Stakeholder groups identified: {len(stakeholder_reqs)}\n"
            f"- Citations: {len(citations)}\n"
            f"- Partial data: {'Yes — see retrieval issues above' if partial_result else 'No'}\n"
            "\n> DECISION SUPPORT ONLY — No schedule change has been approved. "
            "No stakeholders have been notified. No contracts have been modified."
        )

        formatted_output = briefing_draft + metadata_footer

        emit_trace_event(
            "PostProcessNode_output_formatted",
            {
                "review_outcome": review_outcome,
                "output_length": len(formatted_output),
                "partial_result": partial_result,
                "citation_count": len(citations),
            },
            state,
        )

        return {
            "formatted_output": formatted_output,
            "result": to_json(result_payload),
            "status": AgentStatus.SUCCESS.value,
            **provider_metadata(state),
        }
