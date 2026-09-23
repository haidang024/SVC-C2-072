"""HistoryRetrievalNode — retrieves normalized schedule-change history from approved sources."""

# Inner Cat 2 domain node — must use TrustLevel.ANONYMOUS (trust verified at boundary).
# Enforces approved-source allowlisting and bounded queries.
# Stores provenance-bearing records; never stores credentials in state.

from __future__ import annotations

from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.schemas.state import from_json, to_json


class HistoryRetrievalNode(FunctionNode):
    """Retrieve schedule-change history records from operator-configured approved sources.

    - Enforces source allowlisting: only sources in approved_sources_json are queried.
    - Uses ctx.secrets.require() for any source credentials — never os.environ.
    - Normalises raw provider results into serializable, provenance-bearing records.
    - Handles no-result and source-error states with partial-result flagging.
    - Output is decision support only — does not approve any schedule change.
    """

    # Inner domain node — trust already verified at PreProcessNode boundary
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict) -> dict:
        """Query approved schedule-history sources and normalise results."""
        ctx = InvocationContext.from_state(state)

        _ic = state.get("input_context") or {}
        change_scope = from_json(state.get("change_scope_json") or _ic.get("change_scope_json"), default={})
        approved_sources = from_json(state.get("approved_sources_json") or _ic.get("approved_sources_json"), default=[])

        if not approved_sources:
            emit_trace_event(
                "HistoryRetrievalNode_no_sources_configured",
                {"change_type": change_scope.get("change_type", "unknown")},
                state,
            )
            return {
                "schedule_history_json": to_json([]),
                "retrieval_errors_json": to_json(["No approved sources configured for retrieval"]),
                "partial_result": True,
                "status": AgentStatus.SUCCESS.value,
            }

        history_records: list[dict] = []
        retrieval_errors: list[str] = []

        # Retrieve from each approved source using the service adapter
        from src.services.service import ScheduleHistoryService  # local import avoids cycles

        service = ScheduleHistoryService()

        for source_id in approved_sources:
            try:
                # Retrieve api_key for this source (if required) via secrets
                # Pattern: SCHEDULE_SOURCE_{SOURCE_ID_UPPER}_API_KEY
                source_key = f"SCHEDULE_SOURCE_{source_id.upper().replace('-', '_')}_API_KEY"
                source_api_key: str | None = ctx.secrets.get(source_key)

                raw_records = service.fetch_history(
                    source_id=source_id,
                    change_scope=change_scope,
                    api_key=source_api_key,
                )
                normalized = [_normalize_record(r, source_id) for r in (raw_records or [])]
                history_records.extend(normalized)

            except Exception as exc:  # noqa: BLE001
                # Partial failure: record error, continue with remaining sources
                err_msg = f"Source '{source_id}' retrieval failed: {type(exc).__name__}"
                retrieval_errors.append(err_msg)

        has_partial = bool(retrieval_errors)

        emit_trace_event(
            "HistoryRetrievalNode_retrieval_complete",
            {
                "sources_queried": len(approved_sources),
                "records_retrieved": len(history_records),
                "errors_count": len(retrieval_errors),
                "partial_result": has_partial,
                # Do not log raw record content — may contain operator data
            },
            state,
        )

        return {
            "schedule_history_json": to_json(history_records),
            "retrieval_errors_json": to_json(retrieval_errors),
            "partial_result": has_partial,
            "status": AgentStatus.SUCCESS.value,
        }


def _normalize_record(raw: dict, source_id: str) -> dict:
    """Normalise a raw provider record into a provenance-bearing serializable dict.

    Returns a minimal safe structure — never passes raw provider payload through.
    """
    return {
        "source_id": source_id,
        "record_id": str(raw.get("id") or raw.get("record_id") or ""),
        "change_date": str(raw.get("change_date") or raw.get("date") or ""),
        "change_type": str(raw.get("change_type") or raw.get("type") or ""),
        "description": str(raw.get("description") or raw.get("summary") or ""),
        "provenance_url": str(raw.get("provenance_url") or raw.get("url") or ""),
        "confidence": float(raw.get("confidence", 1.0)),
    }
