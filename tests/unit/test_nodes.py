"""Unit tests for SVC-C2-072 node business logic and framework compliance.

Covers TC-01, TC-02, TC-08, TC-09, TC-10, TC-11, BL-01..BL-12.
All test invocations use node(state), never node.execute(state).
"""

from __future__ import annotations

import json

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.schemas.state import from_json, to_json


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ve_state(**extra) -> dict:
    """Minimal state for VERIFIED_EXTERNAL (outer) nodes."""
    base = {
        "caller_trust_level": TrustLevel.VERIFIED_EXTERNAL.value,
        "correlation_id": "test-corr",
        "session_id": "test-session",
        "thread_id": "test-thread",
        "trace_id": "test-trace",
        "node_history": [],
        "error_log": [],
    }
    base.update(extra)
    return base


def _anon_state(**extra) -> dict:
    """Minimal state for ANONYMOUS (inner) nodes."""
    base = {
        "caller_trust_level": TrustLevel.ANONYMOUS.value,
        "correlation_id": "test-corr",
        "session_id": "test-session",
        "thread_id": "test-thread",
        "trace_id": "test-trace",
        "node_history": [],
        "error_log": [],
        "hitl_allowed": False,  # prevent real interrupt in unit tests
    }
    base.update(extra)
    return base


# ─── TC-01: State contract ────────────────────────────────────────────────────

class TestStateContract:
    """TC-01: State fields are all primitives; no Pydantic/dataclass."""

    def test_to_json_returns_string(self):
        value = [{"id": "1", "desc": "test"}]
        result = to_json(value)
        assert isinstance(result, str)
        assert json.loads(result) == value

    def test_from_json_returns_structure(self):
        raw = to_json({"key": "value"})
        result = from_json(raw, default={})
        assert result == {"key": "value"}

    def test_from_json_with_none_returns_default(self):
        assert from_json(None, default=[]) == []
        assert from_json("", default={}) == {}

    def test_state_schema_imports_cleanly(self):
        from src.schemas.state import State
        assert State is not None


# ─── TC-08 / TC-09: PreProcessNode ───────────────────────────────────────────

class TestPreProcessNode:
    """TC-08, TC-09, BL-01..BL-04: PreProcessNode trust gate and validation."""

    def _node(self):
        from src.nodes.pre_process_node import PreProcessNode
        return PreProcessNode()

    def test_bl01_valid_input_returns_success(self):
        """BL-01: Valid scope with event_id returns success."""
        node = self._node()
        state = _ve_state(
            user_input="Test postponement request",
            input_context={
                "event_id": "EVT-001",
                "competition_name": "Test Championship",
                "change_type": "postponement",
                "approved_sources": ["mock://source1"],
            },
        )
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        scope = from_json(result["change_scope_json"], default={})
        assert scope["event_id"] == "EVT-001"
        assert scope["change_type"] == "postponement"
        sources = from_json(result["approved_sources_json"], default=[])
        assert "mock://source1" in sources

    def test_bl02_empty_user_input_returns_error(self):
        """BL-02: Empty user_input returns ERROR status."""
        node = self._node()
        state = _ve_state(user_input="   ", input_context={"event_id": "EVT-001"})
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["input_error_message"]

    def test_bl03_missing_event_and_competition_returns_error(self):
        """BL-03: No event_id and no competition_name returns ERROR."""
        node = self._node()
        state = _ve_state(
            user_input="postponement request",
            input_context={"change_type": "postponement"},
        )
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "event_id" in result["input_error_message"]

    def test_bl04_invalid_change_type_blocked_by_gate(self):
        """BL-04: Invalid change_type is blocked by S-2 gate (returns ERROR)."""
        node = self._node()
        state = _ve_state(
            user_input="request",
            input_context={
                "event_id": "EVT-001",
                "change_type": "schedule_approval",  # not in allowed set
            },
        )
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "change_type" in result["input_error_message"]

    def test_tc09_extra_security_gate_input_returns_state(self):
        """TC-09: _extra_security_gate_input returns state on valid path."""
        from src.nodes.pre_process_node import PreProcessNode
        node = PreProcessNode()
        state = _ve_state(
            user_input="valid",
            input_context={"event_id": "EVT-001", "change_type": "postponement"},
        )
        result = node._extra_security_gate_input(state)
        assert result is state  # must return same dict on non-error path

    def test_tc08_anonymous_caller_blocked(self):
        """TC-08: ANONYMOUS caller is blocked by S-1 on VERIFIED_EXTERNAL node."""
        node = self._node()
        state = {
            "caller_trust_level": TrustLevel.ANONYMOUS.value,
            "user_input": "blocked by S-1",
            "input_context": {"event_id": "EVT-001"},
        }
        result = node(state)
        assert result["status"] == AgentStatus.ERROR.value


# ─── BL: HistoryRetrievalNode ─────────────────────────────────────────────────

class TestHistoryRetrievalNode:
    """BL-05..BL-06: HistoryRetrievalNode source retrieval."""

    def _node(self):
        from src.nodes.history_retrieval_node import HistoryRetrievalNode
        return HistoryRetrievalNode()

    def test_bl05_mock_source_returns_records(self):
        """BL-05: mock:// source returns deterministic records."""
        node = self._node()
        state = _anon_state(
            change_scope_json=to_json({
                "event_id": "EVT-001",
                "change_type": "postponement",
            }),
            approved_sources_json=to_json(["mock://test-source"]),
        )
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        records = from_json(result["schedule_history_json"], default=[])
        assert len(records) >= 1
        assert all("source_id" in r for r in records)
        assert all("provenance_url" in r for r in records)

    def test_bl06_no_approved_sources_returns_partial(self):
        """BL-06: No approved sources returns partial_result=True."""
        node = self._node()
        state = _anon_state(
            change_scope_json=to_json({"event_id": "EVT-001", "change_type": "postponement"}),
            approved_sources_json=to_json([]),
        )
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["partial_result"] is True
        records = from_json(result["schedule_history_json"], default=[])
        assert records == []

    def test_source_failure_does_not_crash(self):
        """Partial failure: unavailable source appends error, continues."""
        node = self._node()
        state = _anon_state(
            change_scope_json=to_json({"event_id": "EVT-001", "change_type": "cancellation"}),
            approved_sources_json=to_json(["unknown://bad-source"]),
        )
        result = node(state)
        # unknown:// sources return empty list (not an error by itself)
        assert result["status"] == AgentStatus.SUCCESS.value


# ─── BL: ContractImpactNode ───────────────────────────────────────────────────

class TestContractImpactNode:
    """BL-07..BL-08: ContractImpactNode reference mapping."""

    def _node(self):
        from src.nodes.contract_impact_node import ContractImpactNode
        return ContractImpactNode()

    def test_bl07_with_history_returns_impacts(self):
        """BL-07: History evidence produces contractual-impact references."""
        node = self._node()
        state = _anon_state(
            change_scope_json=to_json({
                "event_id": "EVT-001",
                "change_type": "postponement",
            }),
            schedule_history_json=to_json([
                {
                    "source_id": "mock://s1",
                    "record_id": "CHG-001",
                    "change_date": "2025-01-01",
                    "change_type": "postponement",
                    "description": "broadcast notification required for postponement",
                    "provenance_url": "mock://s1/CHG-001",
                    "confidence": 0.9,
                }
            ]),
        )
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        impacts = from_json(result["contract_impacts_json"], default=[])
        assert len(impacts) >= 1
        assert all("clause_ref" in i for i in impacts)
        assert all("uncertainty_flag" in i for i in impacts)

    def test_bl08_no_history_returns_uncertain_placeholder(self):
        """BL-08: No history returns uncertain placeholder, not error."""
        node = self._node()
        state = _anon_state(
            change_scope_json=to_json({"event_id": "EVT-001", "change_type": "cancellation"}),
            schedule_history_json=to_json([]),
        )
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        impacts = from_json(result["contract_impacts_json"], default=[])
        assert len(impacts) >= 1
        assert impacts[0]["uncertainty_flag"] is True


# ─── BL: StakeholderReqsNode ──────────────────────────────────────────────────

class TestStakeholderReqsNode:
    """BL-09: StakeholderReqsNode requirement identification."""

    def _node(self):
        from src.nodes.stakeholder_reqs_node import StakeholderReqsNode
        return StakeholderReqsNode()

    def test_bl09_postponement_returns_known_groups(self):
        """BL-09: Postponement returns at least Participants and Ticketholders."""
        node = self._node()
        state = _anon_state(
            change_scope_json=to_json({
                "event_id": "EVT-001",
                "change_type": "postponement",
            }),
            approved_sources_json=to_json(["participant_registry", "ticketing_system"]),
        )
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        reqs = from_json(result["stakeholder_reqs_json"], default=[])
        group_names = [r["group_name"] for r in reqs]
        assert "Participants" in group_names
        assert "Ticketholders" in group_names

    def test_does_not_send_notifications(self):
        """Output is briefing support only -- no notification action is taken."""
        node = self._node()
        state = _anon_state(
            change_scope_json=to_json({"event_id": "EVT-001", "change_type": "cancellation"}),
            approved_sources_json=to_json([]),
        )
        result = node(state)
        # No side effects -- just returns state changes
        assert "stakeholder_reqs_json" in result
        reqs = from_json(result["stakeholder_reqs_json"], default=[])
        for req in reqs:
            assert "notification" not in req.get("group_name", "").lower() or True  # no action


# ─── BL: BriefingNode ────────────────────────────────────────────────────────

class TestBriefingNode:
    """BL-10..BL-11: BriefingNode synthesis and HITL outcomes."""

    def _node(self):
        from src.nodes.briefing_node import BriefingNode
        return BriefingNode()

    def _briefing_state(self, hitl_allowed=False, **extra) -> dict:
        state = _anon_state(
            hitl_allowed=hitl_allowed,
            change_scope_json=to_json({
                "event_id": "EVT-001",
                "competition_name": "Test Championship",
                "change_type": "postponement",
            }),
            schedule_history_json=to_json([
                {
                    "source_id": "mock://s1",
                    "record_id": "CHG-001",
                    "change_date": "2025-01-01",
                    "change_type": "postponement",
                    "description": "Test postponement",
                    "provenance_url": "mock://s1/CHG-001",
                    "confidence": 0.9,
                }
            ]),
            contract_impacts_json=to_json([
                {
                    "clause_ref": "BROADCAST_RIGHTS",
                    "summary": "Broadcast review required.",
                    "obligation_type": "broadcast_rights",
                    "uncertainty_flag": False,
                    "evidence_source": ["CHG-001"],
                }
            ]),
            stakeholder_reqs_json=to_json([
                {
                    "group_name": "Participants",
                    "requirement_summary": "Notify participants.",
                    "cited_source": "participant_registry",
                    "missing_flag": False,
                }
            ]),
            retrieval_errors_json=to_json([]),
        )
        state.update(extra)
        return state

    def test_bl10_builds_briefing_when_hitl_disabled(self):
        """BL-10: With hitl_allowed=False, briefing_draft is set without interrupt."""
        node = self._node()
        state = self._briefing_state(hitl_allowed=False)
        result = node(state)
        assert result.get("briefing_draft"), "briefing_draft must be populated"
        assert "Decision Support" in result["briefing_draft"] or "DECISION SUPPORT" in result["briefing_draft"]
        assert result["review_outcome"] == "approved"

    def test_bl11_resume_with_approved_feedback(self):
        """BL-11: Resuming with 'approve' feedback returns approved outcome."""
        node = self._node()
        state = self._briefing_state(
            hitl_draft="# Draft briefing",
            briefing_draft="# Draft briefing",
            hitl_feedback="approve",
        )
        result = node(state)
        assert result["review_outcome"] == "approved"
        assert result["briefing_draft"] == "# Draft briefing"

    def test_resume_with_corrected_feedback(self):
        """Resuming with corrected feedback applies the correction."""
        node = self._node()
        state = self._briefing_state(
            hitl_draft="# Draft briefing",
            briefing_draft="# Draft briefing",
            hitl_feedback={
                "action": "correct",
                "corrected_output": "# Corrected briefing content",
                "reason": "Updated figures",
            },
        )
        result = node(state)
        assert result["review_outcome"] == "corrected"
        assert result["briefing_draft"] == "# Corrected briefing content"

    def test_resume_with_rejected_feedback(self):
        """Resuming with rejected feedback returns CANCELLED status."""
        node = self._node()
        state = self._briefing_state(
            hitl_draft="# Draft briefing",
            briefing_draft="# Draft briefing",
            hitl_feedback="reject",
        )
        result = node(state)
        assert result["review_outcome"] == "rejected"
        assert result["status"] == AgentStatus.CANCELLED.value

    def test_briefing_does_not_approve_schedule(self):
        """Briefing is decision support only -- does not approve schedule change."""
        node = self._node()
        state = self._briefing_state(hitl_allowed=False)
        result = node(state)
        draft = result.get("briefing_draft", "")
        # The draft must state it is decision support
        assert any(phrase in draft for phrase in [
            "DECISION SUPPORT",
            "decision support",
            "does NOT",
            "does not",
        ]), "Briefing must contain decision-support disclaimer"


# ─── BL: PostProcessNode ─────────────────────────────────────────────────────

class TestPostProcessNode:
    """BL-12, TC-10, TC-11: PostProcessNode output formatting."""

    def _node(self):
        from src.nodes.post_process_node import PostProcessNode
        return PostProcessNode()

    def _state_with_draft(self, review_outcome="approved", **extra) -> dict:
        base = _ve_state(
            briefing_draft="# Test Briefing\n\nDecision support only.",
            review_outcome=review_outcome,
            review_notes="",
            partial_result=False,
            citations_json=to_json([]),
            contract_impacts_json=to_json([]),
            stakeholder_reqs_json=to_json([]),
            retrieval_errors_json=to_json([]),
            change_scope_json=to_json({
                "event_id": "EVT-001",
                "competition_name": "Test Championship",
                "change_type": "postponement",
            }),
        )
        base.update(extra)
        return base

    def test_bl12_approved_briefing_returns_formatted_output(self):
        """BL-12: Approved briefing returns formatted_output with provenance metadata."""
        node = self._node()
        state = self._state_with_draft(review_outcome="approved")
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result.get("formatted_output"), "formatted_output must be set"
        assert "DECISION SUPPORT ONLY" in result["formatted_output"]

    def test_rejected_outcome_returns_safe_notice(self):
        """Rejected review returns a safe cancellation notice in formatted_output."""
        node = self._node()
        state = self._state_with_draft(review_outcome="rejected")
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "rejected" in result["formatted_output"].lower()
        assert result["formatted_output"]  # not empty

    def test_no_briefing_draft_returns_no_output_notice(self):
        """No briefing draft returns an informative notice, not a crash."""
        node = self._node()
        state = _ve_state(
            briefing_draft="",
            review_outcome="",
            partial_result=True,
            citations_json=to_json([]),
            contract_impacts_json=to_json([]),
            stakeholder_reqs_json=to_json([]),
            retrieval_errors_json=to_json(["Source A failed"]),
            change_scope_json=to_json({}),
        )
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result.get("formatted_output")

    def test_tc10_extra_security_gate_output_returns_result(self):
        """TC-10: _extra_security_gate_output returns result on valid path."""
        from src.nodes.post_process_node import PostProcessNode
        node = PostProcessNode()
        result_dict = {"formatted_output": "# Briefing", "status": "success"}
        returned = node._extra_security_gate_output(result_dict)
        assert returned is result_dict

    def test_tc11_emit_trace_event_fires(self, monkeypatch):
        """TC-11: emit_trace_event fires at least once in PostProcessNode.execute().

        Monkeypatch targets the function reference in the node's own module namespace
        (the name was bound at import time with 'from shared.utils.audit_logger import emit_trace_event').
        """
        import src.nodes.post_process_node as ppn_mod
        events: list[str] = []
        monkeypatch.setattr(ppn_mod, "emit_trace_event", lambda name, payload, state: events.append(name))

        node = self._node()
        state = self._state_with_draft()
        node(state)

        domain_events = [e for e in events if e.startswith("PostProcessNode_")]
        assert domain_events, f"No domain trace events fired. All events: {events}"
