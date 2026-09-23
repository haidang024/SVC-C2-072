# PB-6: Invoke Execution Order Verification
# Verifies BaseNode.__call__() enforces: S-1 trust gate -> S-4 node_start ->
# S-2 _security_gate_input() -> execute() -> S-3 _security_gate_output() ->
# S-4 node_complete, for every concrete node under src/nodes/.

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest

from src.schemas.state import to_json


def _discover_node_classes() -> list[type]:
    """Import every module under src/nodes/ and collect concrete BaseNode subclasses."""
    from framework.nodes.base_node import BaseNode

    try:
        pkg = importlib.import_module("src.nodes")
    except ImportError:
        return []

    discovered = []
    for _, modname, _ in pkgutil.walk_packages(pkg.__path__, prefix="src.nodes."):
        module = importlib.import_module(modname)
        for attr in vars(module).values():
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseNode)
                and attr is not BaseNode
                and attr.__module__ == modname
                and not inspect.isabstract(attr)
            ):
                discovered.append(attr)
    return discovered


def _minimal_valid_state(node_cls) -> dict:
    """Build a minimal valid state that satisfies the node's security gates.

    Outer nodes (VERIFIED_EXTERNAL) need user_input + input_context.
    Inner nodes (ANONYMOUS) need the fields they read from state.
    """
    from framework.schemas.trust_level import TrustLevel

    trust_val = node_cls.required_trust_level.value

    # Common fields
    base = {
        "caller_trust_level": trust_val,
        "correlation_id": "pb6-invoke-order-test",
        "session_id": "pb6-session",
        "thread_id": "pb6-thread",
        "trace_id": "pb6-trace",
        "node_history": [],
        "error_log": [],
        "hitl_allowed": False,  # suppress interrupt() in BriefingNode
    }

    node_name = node_cls.__name__

    if node_name == "PreProcessNode":
        base["user_input"] = "Test schedule change request for competition EVT-001"
        base["input_context"] = {
            "event_id": "EVT-001",
            "competition_name": "Test Championship",
            "change_type": "postponement",
            "approved_sources": ["mock://source1"],
        }

    elif node_name == "PostProcessNode":
        base["user_input"] = "test"
        base["briefing_draft"] = "# Test Briefing\n\nDecision support only."
        base["review_outcome"] = "approved"
        base["citations_json"] = to_json([])
        base["contract_impacts_json"] = to_json([])
        base["stakeholder_reqs_json"] = to_json([])
        base["retrieval_errors_json"] = to_json([])
        base["change_scope_json"] = to_json({
            "event_id": "EVT-001",
            "competition_name": "Test Championship",
            "change_type": "postponement",
        })

    elif node_name == "HistoryRetrievalNode":
        base["change_scope_json"] = to_json({
            "event_id": "EVT-001",
            "change_type": "postponement",
        })
        base["approved_sources_json"] = to_json(["mock://source1"])

    elif node_name == "ContractImpactNode":
        base["change_scope_json"] = to_json({
            "event_id": "EVT-001",
            "change_type": "postponement",
        })
        base["schedule_history_json"] = to_json([])

    elif node_name == "StakeholderReqsNode":
        base["change_scope_json"] = to_json({
            "event_id": "EVT-001",
            "change_type": "postponement",
        })
        base["approved_sources_json"] = to_json(["mock://source1"])

    elif node_name == "BriefingNode":
        base["change_scope_json"] = to_json({
            "event_id": "EVT-001",
            "competition_name": "Test Championship",
            "change_type": "postponement",
        })
        base["schedule_history_json"] = to_json([])
        base["contract_impacts_json"] = to_json([])
        base["stakeholder_reqs_json"] = to_json([])
        base["retrieval_errors_json"] = to_json([])

    return base


class TestInvokeOrder:
    """PB-6: __call__ must run S-1 -> node_start -> S-2 -> execute() -> S-3 -> node_complete."""

    def test_call_order_for_every_node(self, monkeypatch, mock_secrets):
        del mock_secrets
        node_classes = _discover_node_classes()
        if not node_classes:
            pytest.skip("no concrete BaseNode subclasses found under src/nodes/")

        import framework.nodes.base_node as base_node_module

        failures: list[str] = []
        for node_cls in node_classes:
            order: list[str] = []
            monkeypatch.setattr(
                base_node_module,
                "emit_trace_event",
                lambda event_type, _payload, _state, _o=order: _o.append(f"event:{event_type}"),
            )

            for method_name, label in (
                ("_security_gate_input", "security_gate_input"),
                ("execute", "execute"),
                ("_security_gate_output", "security_gate_output"),
            ):
                original = getattr(node_cls, method_name)

                def spy(self, arg, _o=order, _label=label, _orig=original):
                    _o.append(_label)
                    return _orig(self, arg)

                monkeypatch.setattr(node_cls, method_name, spy)

            instance = node_cls()
            state = _minimal_valid_state(node_cls)
            instance(state)

            expected = [
                "event:node_start",
                "security_gate_input",
                "execute",
                "security_gate_output",
                "event:node_complete",
            ]
            if order != expected:
                failures.append(
                    f"{node_cls.__name__}: invoke order violation.\n"
                    f"expected: {expected}\nactual:   {order}"
                )

        assert not failures, "\n\n".join(failures)

    def test_s1_rejects_insufficient_trust(self, monkeypatch):
        """PB-6 negative: S-1 must block a node when caller_trust_level is below required.

        PreProcessNode requires VERIFIED_EXTERNAL (1). Calling with ANONYMOUS (0)
        must be rejected without reaching execute().
        """
        from src.nodes.pre_process_node import PreProcessNode
        from framework.schemas.trust_level import TrustLevel
        from framework.schemas.agent_status import AgentStatus

        node = PreProcessNode()
        execute_calls: list[object] = []
        original_execute = node.execute

        def spy_execute(state):
            execute_calls.append(state)
            return original_execute(state)

        monkeypatch.setattr(node, "execute", spy_execute)
        state = {
            "caller_trust_level": TrustLevel.ANONYMOUS.value,  # 0 -- insufficient
            "user_input": "Should be blocked by S-1",
            "input_context": {"event_id": "EVT-001", "competition_name": "Test"},
            "correlation_id": "pb6-s1-rejection-test",
        }
        result = node(state)
        assert result.get("status") == AgentStatus.ERROR.value, (
            "S-1 should reject ANONYMOUS caller for PreProcessNode (VERIFIED_EXTERNAL)"
        )
        assert not execute_calls, "S-1 denial must happen before execute()"
