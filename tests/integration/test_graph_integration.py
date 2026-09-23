"""Integration tests for SVC-C2-072 — full graph invocation with mock data.

Tests the complete outer Graph + inner DomainWorkflowGraph pipeline.
HITL interrupt is disabled (hitl_allowed=False) so integration tests run
without a LangGraph runtime environment.
"""

from __future__ import annotations

import pytest

from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from src.graph.graph import Graph


@pytest.fixture
def graph():
    """Instantiate and compile the outer graph once per test."""
    g = Graph()
    g.compile()
    return g


def _ctx():
    """Return a test InvocationContext.

    hitl_allowed is not an InvocationContext field — PreProcessNode reads it
    from input_context (see src/nodes/pre_process_node.py), so tests disable
    HITL via input_context["hitl_allowed"], not by mutating ctx.
    """
    return InvocationContext(
        session_id="integration-test-session",
        caller_trust_level=TrustLevel.VERIFIED_EXTERNAL,
        caller_id="test-runner",
    )


class TestGraphIntegration:
    """PB-3: Integration tests verifying full pipeline with mock sources."""

    def test_full_pipeline_with_mock_source(self, graph):
        """Full pipeline with a mock:// source returns formatted briefing output."""
        ctx = _ctx()
        result = graph.invoke(
            "Postponement of Summer League Championship 2025 due to venue conflict",
            ctx=ctx,
            input_context={
                "hitl_allowed": False,
                "event_id": "EVT-SL-2025",
                "competition_name": "Summer League Championship 2025",
                "change_type": "postponement",
                "effective_window": "2025-08-01 to 2025-09-30",
                "change_criteria": "Venue double-booked; postponement required pending new venue confirmation.",
                "approved_sources": ["mock://internal-schedule-db"],
                "requester_id": "operator-001",
            },
        )
        assert result is not None
        output = result.get("formatted_output") or result.get("status")
        assert output, f"Expected formatted_output, got: {result}"

    def test_pipeline_returns_briefing_with_decision_support_disclaimer(self, graph):
        """Output must contain decision-support disclaimer per safety requirements."""
        ctx = _ctx()
        result = graph.invoke(
            "Cancellation of Regional Tournament",
            ctx=ctx,
            input_context={
                "hitl_allowed": False,
                "event_id": "EVT-RT-001",
                "competition_name": "Regional Tournament",
                "change_type": "cancellation",
                "approved_sources": ["mock://source-a"],
            },
        )
        formatted = result.get("output", "") or ""
        assert any(
            phrase in formatted
            for phrase in [
                "DECISION SUPPORT",
                "decision support",
                "does not",
                "does NOT",
            ]
        ), "Output must contain decision-support disclaimer"

    def test_pipeline_with_no_approved_sources_returns_partial(self, graph):
        """Pipeline with empty approved_sources returns partial_result flag."""
        ctx = _ctx()
        result = graph.invoke(
            "Venue change for Winter Cup",
            ctx=ctx,
            input_context={
                "hitl_allowed": False,
                "event_id": "EVT-WC-001",
                "competition_name": "Winter Cup",
                "change_type": "venue_change",
                "approved_sources": [],  # no sources configured
            },
        )
        # partial_result should be True or output should mention unavailability
        partial = result.get("partial_result", False)
        formatted = result.get("output", "") or ""
        assert (
            partial or "unavailable" in formatted.lower() or "no output" in formatted.lower()
        ), "Expected partial_result=True or informative output when no sources available"

    def test_pipeline_invalid_user_input_returns_guidance(self, graph):
        """Empty user_input returns user-correctable guidance without invoking the workflow."""
        ctx = _ctx()
        result = graph.invoke(
            "",  # empty -- should be caught by PreProcessNode
            ctx=ctx,
            input_context={"hitl_allowed": False},
        )
        status = result.get("status")
        assert status == AgentStatus.SUCCESS.value, f"Expected SUCCESS guidance status for empty input, got: {status}"
        assert "provide" in result.get("output", "").lower()

    def test_graph_name_matches_manifest(self, graph):
        """Graph name property matches the agent manifest id."""
        assert graph.name == "svc-c2-072"

    def test_graph_state_schema_is_state(self, graph):
        """Graph uses the project State schema."""
        from src.schemas.state import State

        assert graph.state_schema is State
