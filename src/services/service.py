"""ScheduleHistoryService — approved schedule-change history source adapter."""

# Service layer: provider transport outside node logic.
# No business logic, routing, or credentials stored here.
# Nodes call this; this calls approved source endpoints.
# Credentials must be passed in via caller — never stored in service instance.

from __future__ import annotations

from typing import Any


class ScheduleHistoryService:
    """Adapter for retrieving schedule-change history from operator-approved sources.

    Enforces:
    - Source allowlisting is the caller's responsibility (HistoryRetrievalNode)
    - This service accepts source_id + change_scope and returns raw records
    - Raw records are normalised by HistoryRetrievalNode before entering state
    - No credentials stored in service instance — passed per call by caller
    """

    def fetch_history(
        self,
        source_id: str,
        change_scope: dict[str, Any],
        api_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch raw schedule-change history records from a single approved source.

        Args:
            source_id: Allowlisted source identifier (validated by HistoryRetrievalNode)
            change_scope: Normalised change scope dict from state
            api_key: Optional source API key (retrieved via ctx.secrets by caller)

        Returns:
            List of raw provider record dicts (normalised by caller before entering state)

        Raises:
            ConnectionError: On source connectivity failure
            ValueError: On invalid source_id or malformed response
        """
        # Provider routing by source_id prefix
        if source_id.startswith("mock://"):
            return self._fetch_mock(source_id, change_scope)

        # Real provider transport would be implemented here per approved source.
        # Each source gets its own transport method.
        # Example:
        #   if source_id.startswith("internal_db://"):
        #       return self._fetch_internal_db(source_id, change_scope, api_key)
        #   if source_id.startswith("federation://"):
        #       return self._fetch_federation(source_id, change_scope, api_key)

        # Unknown source — return empty list (allowlist enforcement is caller's job)
        return []

    def _fetch_mock(
        self,
        source_id: str,
        change_scope: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Deterministic mock adapter for testing without live sources.

        Returns structurally correct records that pass normalisation.
        """
        change_type = change_scope.get("change_type", "unknown")
        event_id = change_scope.get("event_id", "EVT-000")

        return [
            {
                "id": f"{event_id}-CHG-001",
                "change_date": "2025-06-15",
                "change_type": change_type,
                "description": (
                    f"Schedule {change_type} recorded for event {event_id}. "
                    "Affected participants notified per standard procedure."
                ),
                "provenance_url": f"mock://{source_id}/records/{event_id}-CHG-001",
                "confidence": 0.95,
            },
            {
                "id": f"{event_id}-CHG-002",
                "change_date": "2025-03-10",
                "change_type": change_type,
                "description": (
                    f"Prior {change_type} for same competition series on record. " "Reference for pattern analysis."
                ),
                "provenance_url": f"mock://{source_id}/records/{event_id}-CHG-002",
                "confidence": 0.85,
            },
        ]
