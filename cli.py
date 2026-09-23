"""Marketplace CLI entry point for SVC-C2-072."""

from dataclasses import replace
from typing import Any

from framework.schemas.invocation_context import InvocationContext
from shared.bootstrap.marketplace_app import run_agent_marketplace

from src.graph.graph import Graph


class MarketplaceGraph(Graph):
    """Graph variant for the one-shot Marketplace execution path.

    The Marketplace runner treats ``AWAITING_HUMAN`` as a failure — a one-shot
    execution has no resume channel, so a suspended graph reaches the caller as a
    bare ``RuntimeError`` with the drafted output discarded
    (``shared/bootstrap/marketplace_app.py``). Nothing in the runner sets
    ``hitl_allowed``, so every well-formed request would otherwise fail here.

    Forcing ``hitl_allowed=False`` makes the HITL node take its existing
    no-interrupt branch, returning the draft for review out of band. The
    HTTP/AgentGateway path (``src/api/server.py``) is untouched and keeps full
    HITL suspend/resume, because it has an authenticated resume channel.
    """

    def invoke(
        self,
        user_input: str,
        session_id: str = "",
        ctx: InvocationContext | None = None,
        input_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx = replace(ctx, hitl_allowed=False) if ctx is not None else InvocationContext(hitl_allowed=False)
        result: dict[str, Any] = super().invoke(user_input, session_id=session_id, ctx=ctx, input_context=input_context)
        return result


if __name__ == "__main__":
    run_agent_marketplace(
        MarketplaceGraph,
        agent_name="SVC-C2-072",
        namespace="agent1000",
    )
