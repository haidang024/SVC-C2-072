# Template Design Specification

## Position in AgentCore Architecture

- **Agent Class**: `Graph` (in `src/graph/graph.py`)
- **L1 Base**: AgentBaseGraph (L1-direct)
- **Three-Layer Separation**:
  - State: flat TypedDict composition (no Pydantic — msgpack incompatible)
  - Node: L1 inheritance (Template Method: `execute(self, state: dict) -> dict` override only)
  - Graph: composition (`register_nodes()` for node substitution)

## Architecture Overview

### Node Configuration

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | Framework lifecycle | — | — | InitializeNode (default) |
| pre_process | Validate and normalize change scope and approved-source identifiers | `user_input`, `input_context` | `change_scope_json`, `approved_sources_json`, `validated_input` | PreProcessNode (FunctionNode); `_extra_security_gate_input` domain validation |
| main (GraphNode) | Wraps inner DomainWorkflowGraph | `validated_input`, `change_scope_json`, `approved_sources_json` | `briefing_draft`, `contract_impacts_json`, `stakeholder_reqs_json`, `citations_json`, `review_outcome`, `partial_result` | BriefingWorkflowGraphNode (GraphNode); `get_subgraph`, `extract_input`, `merge_output` |
| ↳ history_retrieval | Retrieve schedule-change records from approved sources | `change_scope_json`, `approved_sources_json` | `schedule_history_json`, `retrieval_errors_json`, `partial_result` | HistoryRetrievalNode (FunctionNode) |
| ↳ contract_impact | Map evidence to contractual-impact references | `change_scope_json`, `schedule_history_json` | `contract_impacts_json` | ContractImpactNode (FunctionNode) |
| ↳ stakeholder_reqs | Identify stakeholder groups and communication requirements | `change_scope_json`, `approved_sources_json` | `stakeholder_reqs_json` | StakeholderReqsNode (FunctionNode) |
| ↳ briefing | Synthesize briefing; request human review via interrupt() | All above + HITL resume fields | `briefing_draft`, `citations_json`, `hitl_draft`, `review_outcome`, `review_notes` | BriefingNode (FunctionNode); HITL D6 pattern |
| post_process | Format final output with provenance metadata | `briefing_draft`, `review_outcome`, `citations_json` | `formatted_output`, `result` | PostProcessNode (FunctionNode); `_extra_security_gate_output` |
| finalize | Framework lifecycle | — | — | FinalizeNode (default) |

### Data Flow

```
START → initialize → pre_process → main (BriefingWorkflowGraphNode)
                                      └─ inner DomainWorkflowGraph
                                           ├─ history_retrieval
                                           ├─ contract_impact
                                           ├─ stakeholder_reqs
                                           └─ briefing ──[interrupt()]──► HUMAN REVIEW
                                    → post_process → finalize → END
```

Inner node trust levels: all ANONYMOUS (trust verified at outer pre_process boundary).

### State Definition

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| change_scope_json | str | JSON-encoded change scope (event_id, competition_name, change_type, effective_window, change_criteria, requester_id) | Yes — from PreProcessNode |
| approved_sources_json | str | JSON-encoded list of allowlisted source identifiers | Yes — from PreProcessNode |
| schedule_history_json | str | JSON-encoded list of normalized history records (source_id, record_id, change_date, change_type, description, provenance_url, confidence) | Yes — from HistoryRetrievalNode |
| contract_impacts_json | str | JSON-encoded list of contractual-impact references (clause_ref, summary, obligation_type, uncertainty_flag, evidence_source) | Yes — from ContractImpactNode |
| stakeholder_reqs_json | str | JSON-encoded list of stakeholder communication requirements (group_name, requirement_summary, cited_source, missing_flag) | Yes — from StakeholderReqsNode |
| briefing_draft | str | Markdown stakeholder briefing document | Yes — from BriefingNode |
| citations_json | str | JSON-encoded citation list (citation_id, source_id, record_id, excerpt, provenance_url) | Yes — from BriefingNode |
| hitl_draft | str | Idempotency guard — briefing draft captured before interrupt() | Yes — from BriefingNode |
| review_outcome | str | Human review result: "approved", "corrected", or "rejected" | Yes — from BriefingNode or HITL resume |
| review_notes | str | Human-provided correction notes (may be empty) | No |
| retrieval_errors_json | str | JSON-encoded list of non-fatal source retrieval error messages | No |
| partial_result | bool | True when some approved sources failed retrieval | No |
| formatted_output | str | Final formatted briefing output (set by PostProcessNode) | Yes — from PostProcessNode |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types)
- No JWT, API keys, credentials in State (checkpoint DB leakage)
- InvocationContext via `InvocationContext.from_state(state)` only inside nodes (not in State)
- No Pydantic models, dataclass, arbitrary Python objects (msgpack incompatible)
- All structured fields declared as `str` and JSON-encoded via `to_json()`/`from_json()`

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (correlation_id, session_id, permissions, credential handle) — HistoryRetrievalNode uses `from_state(state)`
- [x] ConnectionPolicy (retry/timeout strategy) — configured via `config/config.yaml` (`max_retry: 2`, `timeout_s: 120`)
- [x] SecurityViolationError — raised in `_extra_security_gate_input` (PreProcessNode) and `_extra_security_gate_output` (PostProcessNode)
- [x] S-2: `_extra_security_gate_input()` — PreProcessNode enforces change_type allowlist, approved_sources bounds, and input length limits
- [x] S-3: `_extra_security_gate_output()` — PostProcessNode enforces max output length (50,000 chars)
- [x] S-4: `emit_trace_event()` — at least one domain event in every `execute()`:
  - `PreProcessNode_scope_validated` / `PreProcessNode_validation_failed`
  - `HistoryRetrievalNode_retrieval_complete` / `HistoryRetrievalNode_no_sources_configured`
  - `ContractImpactNode_mapping_complete` / `ContractImpactNode_no_evidence`
  - `StakeholderReqsNode_requirements_identified`
  - `BriefingNode_draft_prepared` / `BriefingNode_review_*`
  - `PostProcessNode_output_formatted` / `PostProcessNode_briefing_rejected` / `PostProcessNode_no_briefing_draft`

> **S-2/S-3 gate behaviour (ADR-017):**
> - All nodes are `FunctionNode` subclasses → framework `@final` gate always runs automatically
> - Domain checks extend via `_extra_security_gate_input()` / `_extra_security_gate_output()` only
> - `BriefingWorkflowGraphNode` is a `GraphNode` → deliberate no-op (inner node gates already applied)

### Composition Pattern

- **Pattern**: Cat 2 — AgentBaseGraph (outer) + GraphNode wrapping inner BaseGraph
- **Composition target**: `BriefingWorkflowGraphNode` → `DomainWorkflowGraph` (4-node inner pipeline)
- **Runtime injection**: `BriefingWorkflowGraphNode(config=self.config, llm=self.config.get("llm"))` forwards the complete runtime configuration to the inner graph
- **Error propagation strategy**: `error_strategy = "propagate"` — inner graph errors surface as SubgraphError
- **HITL propagation**: `propagate_hitl = True` — inner BriefingNode interrupt() surfaces to outer caller

## EU AI Act Art.13 Design-Time Evidence

The proposal declares this template outside Annex III scope. The design still
provides explicit transparency and oversight controls:

| Evidence item | Design reference / description |
|---------------|--------------------------------|
| Intended purpose and operating context | Authorized sports-competition operators use the agent to prepare a cited schedule-change stakeholder briefing. |
| System capabilities and limitations | Read-only evidence retrieval and reference mapping; no schedule, contract, notification, or operational changes. |
| User-facing transparency information | The final briefing carries a decision-support disclaimer, citations, uncertainty flags, and partial-data warnings. |
| Human oversight mechanism | `BriefingNode` interrupts after draft synthesis and before final formatting; an authorized reviewer approves, corrects, or rejects it. |

## Source Boundaries and Limitations

### Approved-Source Allowlisting
- Operator configures approved source identifiers in `input_context.approved_sources`
- PreProcessNode validates the list is bounded (≤ 10 sources)
- HistoryRetrievalNode enforces the allowlist — no arbitrary source is queried
- Source secrets declared in `config/agent.yaml` under `requires.secrets`

### Contractual-Impact Limitations
- Output is reference-only: no live contract data is fetched or modified
- Uncertainty is explicitly flagged when evidence is insufficient
- Output explicitly states it is not legal advice

### Partial-Failure Behaviour
- If a source fails, the error is recorded in `retrieval_errors_json`
- `partial_result = True` is set to flag incomplete data
- Pipeline continues with available data; PostProcessNode includes partial-data warning in output
- Human reviewer is informed of data gaps via the briefing document

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: `framework/` and `shared/` only

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | AgentBaseGraph | Fixed 4-step pipeline (history → impact → stakeholders → briefing) — no autonomous loop needed |
| Composition pattern | GraphNode wrapping inner BaseGraph | 4-node flat Cat 1 pipeline | GraphNode + BaseGraph | 4 inner nodes exceed Cat 1 flat-pipeline norm; Cat 2 inner graph provides clean separation of domain steps |
| HITL gate position | At BriefingNode (post-synthesis) | At PostProcessNode (pre-output) | BriefingNode | Human review of the draft before final formatting is most natural and preserves correction ability |
| Partial-failure policy | Fail fast on source error | Continue with partial data + flag | Partial data + flag | Single-source failures should not block the briefing; human reviewer can assess data gaps |
| Inner node trust level | VERIFIED_EXTERNAL (all) | ANONYMOUS (inner only) | ANONYMOUS for inner nodes | Cat 2 architecture: trust verified at pre_process boundary; inner domain nodes are ANONYMOUS |
