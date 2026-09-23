# tests/proof_of_boundary/test_pb7_hitl_interrupt_propagation.py
#
# PB-7: HITL interrupt propagation for SVC-C2-072.
# Runs only when config/config.yaml has hitl.enabled: true.
#
# Two test cases:
#
#   test_pb7_hitl_interrupt_propagates()
#       Verifies that interrupt() raises GraphInterrupt (monkeypatched here) and the
#       signal propagates through BaseNode.__call__() -- NOT caught by the app error boundary.
#
#   test_pb7_hitl_allowed_false_skips_interrupt()
#       Verifies that the hitl_allowed=False guard prevents interrupt() from firing --
#       no GraphInterrupt raised, no deadlock.

from __future__ import annotations

import pathlib
import warnings

import pytest
from framework.schemas.trust_level import TrustLevel
from src.nodes.briefing_node import BriefingNode
from src.schemas.state import to_json

# ---------------------------------------------------------------------------
# Conditional skip -- only runs when config/config.yaml has hitl.enabled: true
# ---------------------------------------------------------------------------

_CONFIG_PATH = pathlib.Path(__file__).parents[2] / "config" / "config.yaml"


def _hitl_enabled() -> bool:
    """Return True when config/config.yaml declares hitl.enabled: true."""
    if not _CONFIG_PATH.exists():
        warnings.warn(f"{_CONFIG_PATH} not found — PB-7 skipped without verifying hitl.enabled.", stacklevel=2)
        return False
    try:
        import yaml
        data = yaml.safe_load(_CONFIG_PATH.read_text())
    except Exception as exc:
        warnings.warn(f"{_CONFIG_PATH} could not be read as YAML ({exc}) — PB-7 skipped.", stacklevel=2)
        return False
    hitl = (data or {}).get("hitl", {}) if isinstance(data, dict) else None
    if not isinstance(hitl, dict):
        warnings.warn(
            f"{_CONFIG_PATH} does not have the expected 'hitl:' mapping shape — PB-7 skipped.",
            stacklevel=2,
        )
        return False
    return bool(hitl.get("enabled", False))


pytestmark = pytest.mark.skipif(
    not _hitl_enabled(),
    reason="config/config.yaml does not set hitl.enabled: true — PB-7 not applicable",
)


def _base_state(**overrides) -> dict:
    """Return a minimal state dict for PB-7 tests."""
    state = {
        "caller_trust_level": TrustLevel.ANONYMOUS.value,
        "correlation_id": "pb7-test",
        "session_id": "pb7-session",
        "thread_id": "pb7-thread",
        "trace_id": "pb7-trace",
        "node_history": [],
        "error_log": [],
        "hitl_allowed": True,  # overridden per test case
        "hitl_count": 0,
        "change_scope_json": to_json({
            "event_id": "EVT-PB7",
            "competition_name": "PB7 Test Championship",
            "change_type": "postponement",
        }),
        "schedule_history_json": to_json([]),
        "contract_impacts_json": to_json([]),
        "stakeholder_reqs_json": to_json([]),
        "retrieval_errors_json": to_json([]),
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# PB-7-A: interrupt() raises GraphInterrupt and propagates
# ---------------------------------------------------------------------------


def test_pb7_hitl_interrupt_propagates(monkeypatch) -> None:
    """PB-7: interrupt() raises GraphInterrupt and propagates (not caught by app boundary).

    Asserts the first PB-7 requirement directly:
      GraphInterrupt reaches LangGraph engine; status is NOT set to error.

    We monkeypatch langgraph.types.interrupt to raise GraphInterrupt so the
    test is deterministic without a running LangGraph engine.
    """
    from langgraph.errors import GraphInterrupt
    import langgraph.types as lg_types

    raised: list[bool] = []

    def _mock_interrupt(payload):
        raised.append(True)
        raise GraphInterrupt(payload)

    monkeypatch.setattr(lg_types, "interrupt", _mock_interrupt)
    # Also patch the import in briefing_node module
    import src.nodes.briefing_node as bn_mod
    monkeypatch.setattr(bn_mod, "interrupt", _mock_interrupt)

    node = BriefingNode()
    state = _base_state(hitl_allowed=True)

    with pytest.raises(GraphInterrupt):
        node(state)  # must call via __call__(), not execute() directly

    assert raised, "interrupt() was never called"


# ---------------------------------------------------------------------------
# PB-7-B: hitl_allowed=False guard prevents deadlock
# ---------------------------------------------------------------------------


def test_pb7_hitl_allowed_false_skips_interrupt(monkeypatch) -> None:
    """PB-7 guard: hitl_allowed=False must NOT raise GraphInterrupt (no deadlock).

    Asserts the guard requirement directly:
      When hitl_allowed=False, BriefingNode must skip the interrupt() call
      and return the briefing draft directly.
    """
    called: list[bool] = []

    def _should_not_be_called(payload):
        called.append(True)
        raise AssertionError("interrupt() must NOT be called when hitl_allowed=False")

    import src.nodes.briefing_node as bn_mod
    monkeypatch.setattr(bn_mod, "interrupt", _should_not_be_called)

    node = BriefingNode()
    state = _base_state(hitl_allowed=False)

    result = node(state)  # must NOT raise GraphInterrupt

    assert not called, "interrupt() was called despite hitl_allowed=False"
    assert result.get("briefing_draft") is not None, "briefing_draft must be set when HITL is skipped"
    assert result.get("review_outcome") == "approved", "review_outcome must be 'approved' when HITL is skipped"
