"""Graph — outer Cat 2 AgentBaseGraph for SVC-C2-072 Sports Competition Schedule Change Stakeholder Briefing Agent."""

# Architecture: Cat 2 -- AgentBaseGraph (outer) + BaseGraph inner workflow.
# Fixed backbone: START -> initialize -> pre_process -> main -> post_process -> finalize -> END
# Domain logic is encapsulated in BriefingWorkflowGraphNode (main slot).
# Do NOT override add_edges() -- backbone wiring is owned by the framework.

from __future__ import annotations

from typing import Any, ClassVar

from framework.errors import SubgraphError
from framework.graph.agent_base_graph import AgentBaseGraph
from framework.graph.base_graph import BaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State


class BriefingWorkflowGraphNode(GraphNode):
    """GraphNode wrapper for the inner DomainWorkflowGraph briefing pipeline.

    Assigned to the main slot of the outer AgentBaseGraph.
    The inner graph runs: history_retrieval -> contract_impact -> stakeholder_reqs -> briefing
    """

    # Re-raise inner graph exceptions as SubgraphError (fail fast)
    error_strategy: ClassVar[str] = "propagate"

    # Surface inner HITL interrupt to the outer caller so the platform can
    # present the human-review prompt and resume correctly.
    propagate_hitl: ClassVar[bool] = True

    def __init__(self, config: dict[str, Any] | None = None, llm: Any = None) -> None:
        super().__init__()
        self._config = dict(config or {})
        self._llm = llm
        self._config["llm"] = llm

    def get_subgraph(self) -> BaseGraph:
        """Instantiate and return the inner domain workflow graph."""
        from src.graph.domain_workflow_graph import DomainWorkflowGraph  # local import avoids cycles

        return DomainWorkflowGraph(config=self._parent_config())

    def extract_input(self, state: AgentState) -> str:
        """Return the validated change criteria string to pass into inner_graph.invoke()."""
        return state.get("validated_input", state.get("user_input", ""))

    def merge_output(self, state: AgentState, sub_result: dict) -> dict:
        """Map inner graph sub_result -> outer state. Return ONLY changed keys.

        Designed together with DomainWorkflowGraph.get_output().
        """
        return {
            "result": sub_result.get("output"),
            "status": sub_result.get("status"),
            "briefing_draft": sub_result.get("briefing_draft"),
            "citations_json": sub_result.get("citations_json"),
            "contract_impacts_json": sub_result.get("contract_impacts_json"),
            "stakeholder_reqs_json": sub_result.get("stakeholder_reqs_json"),
            "retrieval_errors_json": sub_result.get("retrieval_errors_json"),
            "review_outcome": sub_result.get("review_outcome"),
            "review_notes": sub_result.get("review_notes"),
            "partial_result": sub_result.get("partial_result", False),
        }

    def execute(self, state: AgentState) -> dict:
        """Override to forward domain state fields into the inner graph via input_context."""
        if state.get("input_error_message"):
            return {"status": AgentStatus.SUCCESS.value}
        subgraph_hitl_allowed = self.propagate_hitl and state.get("hitl_allowed", True)
        _base_ctx = InvocationContext.from_state(state)
        ctx = InvocationContext(
            correlation_id=_base_ctx.correlation_id,
            session_id=_base_ctx.session_id,
            thread_id=_base_ctx.thread_id,
            caller_trust_level=_base_ctx.caller_trust_level,
            caller_id=_base_ctx.caller_id,
            hitl_allowed=subgraph_hitl_allowed,
        )
        subgraph = self.get_subgraph()
        user_input = self.extract_input(state)

        # Forward PreProcessNode outputs so inner nodes can read them from state
        inner_input_context = {
            "change_scope_json": state.get("change_scope_json", ""),
            "approved_sources_json": state.get("approved_sources_json", ""),
        }

        try:
            sub_result = subgraph.invoke(
                user_input,
                session_id=ctx.session_id,
                ctx=ctx,
                input_context=inner_input_context,
            )
        except Exception as e:
            return self._handle_call_error(subgraph, e, state)

        if self.propagate_hitl and sub_result.get("status") == AgentStatus.AWAITING_HUMAN.value:
            from langgraph.types import interrupt as lg_interrupt

            _hitl_meta = sub_result.get("hitl_metadata") or {}
            lg_interrupt({"subgraph_thread_id": sub_result.get("thread_id", ""), **_hitl_meta})

        if sub_result.get("status") == AgentStatus.ERROR.value:
            error = SubgraphError(
                agent_name=subgraph.name,
                error_log=sub_result.get("error_log", []),
                trace_id=sub_result.get("trace_id", ""),
            )
            if self.error_strategy == "propagate":
                raise error
            return self.on_subgraph_error(state, error)

        return self.merge_output(state, sub_result)

    def _parent_config(self) -> dict[str, Any]:
        """Forward runtime configuration, including the injected LLM."""
        return self._config


class Graph(AgentBaseGraph):
    """Outer Cat 2 AgentBaseGraph for SVC-C2-072.

    Direct L1 inheritance from AgentBaseGraph. Domain logic is encapsulated in the
    BriefingWorkflowGraphNode (main slot), which wraps the DomainWorkflowGraph inner pipeline.

    Backbone (fixed -- do not override add_edges()):
        START -> initialize -> pre_process -> main -> post_process -> finalize -> END
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config: dict[str, Any] = config or {}
        super().__init__(config=self._config)

    @property
    def name(self) -> str:
        return "svc-c2-072"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        """Register all outer nodes. Call super() first to inject initialize + finalize."""
        super().register_nodes()  # injects InitializeNode + FinalizeNode
        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = BriefingWorkflowGraphNode(
            config=self.config,
            llm=self.config.get("llm"),
        )
        self._nodes["post_process"] = PostProcessNode(
            llm=self.config.get("llm"),
            config=self.config,
        )

    def get_output(self, state: AgentState) -> dict[str, Any]:
        output = {
            "output": state.get("formatted_output") or state.get("result", ""),
            "result": state.get("result", ""),
            "status": state.get("status", AgentStatus.ERROR.value),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
            "generation_mode": state.get("generation_mode"),
            "provider_error_message": state.get("provider_error_message"),
        }
        _set_marketplace_guidance(output, state, "Schedule-change briefing request")
        return output


def _set_marketplace_guidance(output: dict[str, Any], state: AgentState, subject: str) -> None:
    context = state.get("input_context")
    message = state.get("input_error_message")
    if not (isinstance(context, dict) and "conversation_history" in context and message):
        return
    lines = [f"{subject} could not be processed.", "", f"Reason: {message}"]
    guidance = state.get("input_error_guidance")
    if isinstance(guidance, str) and guidance:
        lines.extend(["", "How to continue:"])
        lines.extend(f"- {item}" for item in guidance.splitlines())
    output["output"] = "\n".join(lines)

    # add_edges() is NOT overridden -- backbone wiring belongs to the framework
