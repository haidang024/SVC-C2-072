"""DomainWorkflowGraph — inner Cat 2 workflow for SVC-C2-072 schedule-change briefing."""

# Inner graph for SVC-C2-072. Called by BriefingWorkflowGraphNode.get_subgraph() in graph.py.
# Inherits BaseGraph for a fully custom 4-node linear topology:
#   START → history_retrieval → contract_impact → stakeholder_reqs → briefing → END
#
# All inner nodes must use TrustLevel.ANONYMOUS (trust verified at outer PreProcessNode boundary).
# This graph does NOT inherit AgentBaseGraph — no initialize/finalize slots needed.

from __future__ import annotations

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from src.nodes.briefing_node import BriefingNode
from src.nodes.contract_impact_node import ContractImpactNode
from src.nodes.history_retrieval_node import HistoryRetrievalNode
from src.nodes.stakeholder_reqs_node import StakeholderReqsNode
from src.schemas.state import State


class DomainWorkflowGraph(BaseGraph):
    """Inner domain workflow for SVC-C2-072 — 4-node briefing pipeline.

    Pipeline:
        START → history_retrieval → contract_impact → stakeholder_reqs → briefing → END

    Called by BriefingWorkflowGraphNode.get_subgraph() in graph.py.
    Output shaped by get_output() and consumed by BriefingWorkflowGraphNode.merge_output().
    """

    @property
    def name(self) -> str:
        return "svc_c2_072_briefing_workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        """No mandatory config for the inner graph — approved sources come via state."""
        pass

    def register_nodes(self) -> None:
        """Register all inner domain nodes. No super() call — BaseGraph is abstract.

        All nodes use TrustLevel.ANONYMOUS per Cat 2 trust-level architecture.
        Do NOT register initialize / finalize here.
        """
        self._nodes["history_retrieval"] = HistoryRetrievalNode()
        self._nodes["contract_impact"] = ContractImpactNode()
        self._nodes["stakeholder_reqs"] = StakeholderReqsNode()
        self._nodes["briefing"] = BriefingNode()

    def add_edges(self) -> None:
        """Wire the 4-node linear topology.

        Linear pipeline: history_retrieval → contract_impact → stakeholder_reqs → briefing → END
        All nodes must be reachable from START.
        """
        self._sg.add_edge(START, "history_retrieval")
        self._sg.add_edge("history_retrieval", "contract_impact")
        self._sg.add_edge("contract_impact", "stakeholder_reqs")
        self._sg.add_edge("stakeholder_reqs", "briefing")
        self._sg.add_edge("briefing", END)

    def route(self, state: AgentState) -> str:
        """Conditional routing — required by BaseGraph ABC.

        For this linear topology, route() is never called by add_edges() but is
        required as an abstract-method implementation.
        Short-circuits to END on error status.
        """
        return str(END) if state.get("status") == AgentStatus.ERROR.value else "briefing"

    def get_output(self, state: AgentState) -> dict:
        """Shape the sub_result dict for BriefingWorkflowGraphNode.merge_output().

        Keys MUST match what merge_output() reads from sub_result.
        """
        return {
            "output": state.get("briefing_draft"),
            "status": state.get("status", AgentStatus.SUCCESS.value),
            "briefing_draft": state.get("briefing_draft"),
            "citations_json": state.get("citations_json"),
            "contract_impacts_json": state.get("contract_impacts_json"),
            "stakeholder_reqs_json": state.get("stakeholder_reqs_json"),
            "retrieval_errors_json": state.get("retrieval_errors_json"),
            "review_outcome": state.get("review_outcome"),
            "review_notes": state.get("review_notes"),
            "partial_result": state.get("partial_result", False),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
