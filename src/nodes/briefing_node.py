"""BriefingNode — synthesizes evidence into a review-ready stakeholder briefing and requests human review."""

# Inner Cat 2 domain node — must use TrustLevel.ANONYMOUS (trust verified at boundary).
# HITL: interrupt() is guarded by state.get("hitl_allowed", True) — D6 pattern.
# This node produces decision support ONLY. It does NOT:
#   - Approve a schedule change
#   - Notify stakeholders
#   - Modify contracts
#   - Make operational commitments

from __future__ import annotations

from typing import ClassVar

from langgraph.types import interrupt

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.schemas.state import from_json, to_json


class BriefingNode(FunctionNode):
    """Synthesize schedule history, contractual references, and stakeholder requirements
    into a factual bounded impact model and a review-ready stakeholder briefing.

    Behaviour:
    - Separates source-supported facts from assumptions and knowledge gaps
    - Retains citations and provenance for all stated claims
    - Never generates unsupported financial, legal, or operational conclusions
    - Requests human review via interrupt() before final output
    - Uses hitl_draft as idempotency guard — prevents duplicate interrupt on resume
    - Handles approved, corrected, and rejected HITL resume outcomes
    """

    # Inner domain node — trust already verified at PreProcessNode boundary
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict) -> dict:
        """Build the stakeholder briefing document and request human review."""
        _ic = state.get("input_context") or {}
        change_scope = from_json(state.get("change_scope_json") or _ic.get("change_scope_json"), default={})
        history_records = from_json(state.get("schedule_history_json"), default=[])
        contract_impacts = from_json(state.get("contract_impacts_json"), default=[])
        stakeholder_reqs = from_json(state.get("stakeholder_reqs_json"), default=[])
        retrieval_errors = from_json(state.get("retrieval_errors_json"), default=[])
        partial_result = state.get("partial_result", False)

        # ── Idempotency guard — if we already built the draft before interrupt, ──
        # check for HITL resume feedback first
        existing_draft = state.get("hitl_draft") or state.get("briefing_draft")
        hitl_feedback = state.get("hitl_feedback")
        if existing_draft and hitl_feedback is not None:
            # Resuming after human review
            return self._handle_review_resume(state, existing_draft, hitl_feedback)

        # ── Build the briefing document ─────────────────────────────────────────
        briefing_draft, citations = _build_briefing(
            change_scope=change_scope,
            history_records=history_records,
            contract_impacts=contract_impacts,
            stakeholder_reqs=stakeholder_reqs,
            retrieval_errors=retrieval_errors,
            partial_result=partial_result,
        )

        emit_trace_event(
            "BriefingNode_draft_prepared",
            {
                "history_record_count": len(history_records),
                "contract_impact_count": len(contract_impacts),
                "stakeholder_group_count": len(stakeholder_reqs),
                "citation_count": len(citations),
                "partial_result": partial_result,
                # Do not log briefing content — may contain operator data
            },
            state,
        )

        # ── HITL interrupt — guarded by hitl_allowed (D6 pattern) ──────────────
        if state.get("hitl_allowed", True):
            # Raise interrupt — LangGraph captures checkpoint; client receives
            # status: "awaiting_human" + hitl_metadata. Resume paths handled above.
            interrupt(
                {
                    "action": "review_briefing",
                    "prompt": (
                        "Please review the stakeholder briefing draft below.\n"
                        "This document is decision support only — it does NOT approve any "
                        "schedule change or initiate stakeholder communications.\n\n"
                        f"{briefing_draft}\n\n"
                        "Respond with:\n"
                        "  - 'approve' to accept the briefing as-is\n"
                        "  - 'correct' + corrected_output to provide amendments\n"
                        "  - 'reject' to discard and terminate"
                    ),
                    "briefing_length": len(briefing_draft),
                    "partial_data": partial_result,
                }
            )
            # Execution continues here only after resume (feedback injected into state)
            # The updated state with hitl_feedback will be processed on the next call

        # hitl_allowed=False: skip interrupt, proceed with draft directly
        return {
            "briefing_draft": briefing_draft,
            "hitl_draft": briefing_draft,  # idempotency guard
            "citations_json": to_json(citations),
            "review_outcome": "approved",  # auto-approved when HITL is disabled
            "status": AgentStatus.SUCCESS.value,
        }

    def _handle_review_resume(self, state: dict, draft: str, hitl_feedback) -> dict:
        """Process human review feedback after interrupt resume."""
        # Normalise feedback — may be a string verb or a dict
        if isinstance(hitl_feedback, dict):
            action = str(hitl_feedback.get("action", "")).lower()
            corrected_output = hitl_feedback.get("corrected_output")
            review_notes = str(hitl_feedback.get("reason", ""))
        else:
            action = str(hitl_feedback).lower()
            corrected_output = None
            review_notes = ""

        if action in ("approve", "approved"):
            emit_trace_event(
                "BriefingNode_review_approved",
                {"action": "approved"},
                state,
            )
            return {
                "briefing_draft": draft,
                "review_outcome": "approved",
                "review_notes": review_notes,
                "status": AgentStatus.SUCCESS.value,
            }

        elif action in ("correct", "corrected") and corrected_output:
            corrected = str(corrected_output).strip()
            emit_trace_event(
                "BriefingNode_review_corrected",
                {"action": "corrected", "correction_length": len(corrected)},
                state,
            )
            return {
                "briefing_draft": corrected,
                "review_outcome": "corrected",
                "review_notes": review_notes,
                "status": AgentStatus.SUCCESS.value,
            }

        elif action in ("reject", "rejected"):
            emit_trace_event(
                "BriefingNode_review_rejected",
                {"action": "rejected"},
                state,
            )
            return {
                "briefing_draft": draft,
                "review_outcome": "rejected",
                "review_notes": review_notes,
                "status": AgentStatus.CANCELLED.value,
            }

        else:
            # Unknown feedback — treat as approval with a note
            emit_trace_event(
                "BriefingNode_review_unknown_feedback",
                {"action": action},
                state,
            )
            return {
                "briefing_draft": draft,
                "review_outcome": "approved",
                "review_notes": f"Unknown feedback action '{action}' — treated as approved.",
                "status": AgentStatus.SUCCESS.value,
            }


def _build_briefing(
    change_scope: dict,
    history_records: list,
    contract_impacts: list,
    stakeholder_reqs: list,
    retrieval_errors: list,
    partial_result: bool,
) -> tuple[str, list]:
    """Build the structured markdown briefing document and citation list.

    Separates source-supported facts from knowledge gaps.
    Returns (briefing_text, citations_list).
    """
    event_id = change_scope.get("event_id", "N/A")
    competition_name = change_scope.get("competition_name", "N/A")
    change_type = change_scope.get("change_type", "unknown")
    effective_window = change_scope.get("effective_window", "Not specified")
    change_criteria = change_scope.get("change_criteria", "")

    citations: list[dict] = []
    citation_counter = 0

    def _add_citation(source_id: str, record_id: str, excerpt: str, url: str = "") -> str:
        nonlocal citation_counter
        citation_counter += 1
        cid = f"[{citation_counter}]"
        citations.append(
            {
                "citation_id": cid,
                "source_id": source_id,
                "record_id": record_id,
                "excerpt": excerpt[:200],
                "provenance_url": url,
            }
        )
        return cid

    lines: list[str] = [
        "# Sports Competition Schedule Change — Stakeholder Briefing",
        "",
        "> **DECISION SUPPORT ONLY** — This briefing is produced by an automated agent "
        "for human review. It does NOT constitute schedule approval, contract modification, "
        "stakeholder notification, or any operational commitment.",
        "",
        "---",
        "",
        "## 1. Change Summary",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Event ID | {event_id} |",
        f"| Competition | {competition_name} |",
        f"| Change Type | {change_type} |",
        f"| Effective Window | {effective_window} |",
        f"| Change Criteria | {change_criteria[:300] if change_criteria else 'N/A'} |",
        "",
    ]

    if partial_result:
        lines += [
            "⚠️ **Partial Data Warning:** Some approved sources were unavailable. "
            "This briefing is based on incomplete data. Human review should validate coverage.",
            "",
        ]

    # ── Section 2: Schedule History ────────────────────────────────────────────
    lines += ["## 2. Schedule-Change History", ""]

    if history_records:
        lines += [
            "| Date | Change Type | Description | Source | Citation |",
            "|------|-------------|-------------|--------|---------|",
        ]
        for rec in history_records[:20]:  # cap display rows
            cid = _add_citation(
                source_id=rec.get("source_id", ""),
                record_id=rec.get("record_id", ""),
                excerpt=rec.get("description", ""),
                url=rec.get("provenance_url", ""),
            )
            lines.append(
                f"| {rec.get('change_date', 'N/A')} "
                f"| {rec.get('change_type', 'N/A')} "
                f"| {rec.get('description', 'N/A')[:100]} "
                f"| {rec.get('source_id', 'N/A')} "
                f"| {cid} |"
            )
        if len(history_records) > 20:
            lines.append(f"_... and {len(history_records) - 20} additional records (see full data)._")
    else:
        lines += [
            "_No schedule-change history records retrieved from approved sources._",
            "",
            "**Gap:** History evidence is unavailable — contractual impact mapping "
            "has been performed with uncertainty flags.",
        ]
    lines.append("")

    # ── Section 3: Contractual Impact References ───────────────────────────────
    lines += [
        "## 3. Contractual-Impact References",
        "",
        "> Reference only. Not legal advice. Uncertainty flags indicate insufficient evidence.",
        "",
    ]

    if contract_impacts:
        lines += [
            "| Clause Reference | Obligation Type | Summary | Uncertainty |",
            "|-----------------|-----------------|---------|-------------|",
        ]
        for impact in contract_impacts:
            uncertainty_label = "⚠️ Uncertain" if impact.get("uncertainty_flag") else "Supported"
            lines.append(
                f"| {impact.get('clause_ref', 'N/A')} "
                f"| {impact.get('obligation_type', 'N/A')} "
                f"| {impact.get('summary', 'N/A')[:120]} "
                f"| {uncertainty_label} |"
            )
    else:
        lines += ["_No contractual-impact references identified._"]
    lines.append("")

    # ── Section 4: Stakeholder Communication Requirements ─────────────────────
    lines += [
        "## 4. Stakeholder Communication Requirements",
        "",
        "> Requirements listed for human action. This agent does NOT send notifications.",
        "",
    ]

    if stakeholder_reqs:
        lines += [
            "| Stakeholder Group | Requirement Summary | Source | Status |",
            "|-------------------|---------------------|--------|--------|",
        ]
        for req in stakeholder_reqs:
            status = "⚠️ Unverified" if req.get("missing_flag") else "Referenced"
            cited = req.get("cited_source") or "N/A"
            lines.append(
                f"| {req.get('group_name', 'N/A')} "
                f"| {req.get('requirement_summary', 'N/A')[:150]} "
                f"| {cited} "
                f"| {status} |"
            )
    else:
        lines += ["_No stakeholder communication requirements identified._"]
    lines.append("")

    # ── Section 5: Retrieval Issues (if any) ──────────────────────────────────
    if retrieval_errors:
        lines += ["## 5. Data Retrieval Issues", ""]
        for err in retrieval_errors:
            lines.append(f"- {err}")
        lines += [
            "",
            "_Human reviewers should assess whether missing source data affects the " "completeness of this briefing._",
            "",
        ]

    # ── Section 6: Citations ──────────────────────────────────────────────────
    if citations:
        lines += ["## 6. Citations", ""]
        for c in citations:
            url_part = f" — {c['provenance_url']}" if c.get("provenance_url") else ""
            lines.append(f"{c['citation_id']} Source: {c['source_id']} | " f"Record: {c['record_id']}{url_part}")
        lines.append("")

    # ── Section 7: Limitations ────────────────────────────────────────────────
    lines += [
        "## 7. Limitations",
        "",
        "- This briefing is produced from operator-configured approved sources only.",
        "- It does not constitute legal advice, schedule approval, or a commitment of any kind.",
        "- Contractual references are based on historical evidence and may be incomplete.",
        "- Human review and expert consultation are required before any operational action.",
    ]

    return "\n".join(lines), citations
