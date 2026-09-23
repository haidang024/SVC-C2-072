"""State — flat TypedDict schema for SVC-C2-072 Sports Competition Schedule Change Stakeholder Briefing Agent."""

# ADR-005: State must be a flat TypedDict (see ADR-005 for prohibited alternatives).
# LangGraph checkpoints use msgpack serialization — only plain serializable fields allowed.
# ALL structured fields MUST be JSON-encoded strings (to_json/from_json).
# Do NOT add credentials, secrets, or InvocationContext here.

from __future__ import annotations

import json

from framework.schemas.agent_state import AgentState


# ─── msgpack-safety helpers (MANDATORY — must be present in every state.py) ───


def to_json(value) -> str:
    """Encode structured value to JSON string before storing in State."""
    return json.dumps(value, ensure_ascii=False)


def from_json(value: str | None, default=None):
    """Decode JSON string from State back to structured value."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


# ─── State schema ──────────────────────────────────────────────────────────────
# Rules:
#   - ALL fields must be primitives: str, int, float, bool, or None
#   - Structured data (dict, list) → JSON-encode with to_json(); declare field as str
#   - NEVER use: List[dict], dict, list, Optional[dict], Pydantic, dataclass
#   - NEVER store: JWT, API keys, InvocationContext, credentials


class State(AgentState):
    """Agent state for SVC-C2-072.

    Producer/consumer ownership:
      - change_scope_json      : PreProcessNode (produces) → all inner nodes (consume)
      - approved_sources_json  : PreProcessNode (produces) → HistoryRetrievalNode (consumes)
      - schedule_history_json  : HistoryRetrievalNode (produces) → ContractImpactNode, BriefingNode (consume)
      - contract_impacts_json  : ContractImpactNode (produces) → BriefingNode (consumes)
      - stakeholder_reqs_json  : StakeholderReqsNode (produces) → BriefingNode (consumes)
      - briefing_draft         : BriefingNode (produces) → PostProcessNode (consumes)
      - citations_json         : BriefingNode (produces) → PostProcessNode (consumes)
      - review_outcome         : BriefingNode (consumes/produces after HITL resume)
      - review_notes           : BriefingNode (consumes after HITL resume)
      - hitl_draft             : BriefingNode (produces — idempotency guard before interrupt)
      - retrieval_errors_json  : HistoryRetrievalNode (produces) → PostProcessNode (consumes)
      - formatted_output       : PostProcessNode (produces) — final API response field
      - partial_result         : bool flag — PostProcessNode (produces)
    """

    # ── Input / scope ──────────────────────────────────────────────────────────
    # JSON-encoded dict: {event_id, competition_name, change_type, effective_window,
    #                     change_criteria, requester_id}
    change_scope_json: str

    # JSON-encoded list[str]: allowlisted source identifiers configured by business operator
    approved_sources_json: str

    # ── Processing — schedule history ──────────────────────────────────────────
    # JSON-encoded list[dict]: normalized schedule-change records with provenance fields
    # {source_id, record_id, change_date, change_type, description, provenance_url}
    schedule_history_json: str

    # ── Processing — contractual impact references ─────────────────────────────
    # JSON-encoded list[dict]: referenced clauses/obligations (no live contract data)
    # {clause_ref, summary, obligation_type, uncertainty_flag, evidence_source}
    contract_impacts_json: str

    # ── Processing — stakeholder & communication requirements ──────────────────
    # JSON-encoded list[dict]: identified stakeholder groups and communication requirements
    # {group_name, requirement_summary, cited_source, missing_flag}
    stakeholder_reqs_json: str

    # ── Processing — briefing ──────────────────────────────────────────────────
    # Markdown-formatted draft briefing document (human-readable text)
    briefing_draft: str

    # JSON-encoded list[dict]: citation records
    # {citation_id, source_id, record_id, excerpt, provenance_url}
    citations_json: str

    # ── HITL review ───────────────────────────────────────────────────────────
    # Idempotency guard — set before interrupt() to detect already-drafted state on resume
    hitl_draft: str

    # HitlStatus value string: "approved" | "corrected" | "rejected"
    review_outcome: str

    # Human-provided correction notes (populated on corrected resume)
    review_notes: str

    # ── Output ────────────────────────────────────────────────────────────────
    # Final formatted briefing output (set by PostProcessNode)
    formatted_output: str

    # True when output is based on partial source data (some sources failed)
    partial_result: bool

    # JSON-encoded list[str]: non-fatal source retrieval errors for transparency
    retrieval_errors_json: str

    # User-correctable input guidance (newline-delimited for flat state compatibility)
    input_error_message: str
    input_error_guidance: str

    # Invocation-scoped provider observability (never contains secret details)
    generation_mode: str
    provider_error_message: str
