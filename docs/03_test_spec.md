# Test Specification

## Test Strategy
- Coverage target: 90%+ (not measured in the verification run recorded below)
- Test types: Unit / Integration / Proof-of-Boundary

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict with `to_json`/`from_json` helpers | Type check pass, no Pydantic/dataclass; both helpers present and functional | ✅ Pass |
| TC-02 | SecurityViolationError fires on invalid input (empty user_input, invalid change_type) | Error raised via S-2 gate; returns ERROR status | ✅ Pass (BL-02, BL-04) |
| TC-03 | No JWT/Credential in State | CI `gate-credential-scan`: 0 violations | ✅ Pass (PB-5) |
| TC-04 | InvocationContext via configurable only | `InvocationContext.from_state(state)` used in HistoryRetrievalNode; no direct construction | ✅ Pass |
| TC-05 | S-4: no duplicate lifecycle events in `execute()` | `node_start` / `node_complete` / `node_error` absent from all `execute()` bodies | ✅ Pass |
| TC-06 | S-2: `_security_gate_input()` not overridden (FunctionNode subclass) | `TypeError` raised at class definition if overridden | ✅ Pass (test_framework_compliance_tc06_tc07.py) |
| TC-07 | S-3: `_security_gate_output()` not overridden (FunctionNode subclass) | `TypeError` raised at class definition if overridden | ✅ Pass (test_framework_compliance_tc06_tc07.py) |
| TC-08 | `required_trust_level` enforced | ANONYMOUS caller → refused by PreProcessNode (VERIFIED_EXTERNAL) | ✅ Pass (BL-04, PB-6 negative) |
| TC-09 | S-2: `_extra_security_gate_input()` non-trivial | change_type allowlist, approved_sources bounds, input length enforced | ✅ Pass (TC-09 test) |
| TC-10 | S-3: `_extra_security_gate_output()` non-trivial | Max output length enforced on PostProcessNode | ✅ Pass (TC-10 test) |
| TC-11 | S-4: at least one domain `emit_trace_event()` inside each `execute()` | All 6 nodes emit domain-specific events | ✅ Pass (TC-11 test + PB-1 coverage) |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on every invocation path | Domain events present in all nodes | ✅ Pass (TC-11 test) |
| PB-2 | State serialization | Post-invoke State is primitives only | No Pydantic/dataclass in state.py | ✅ Pass (test_state_safety.py) |
| PB-3 | Level 2 → External service | Mock-source adapter returns normalized records with provenance | Data retrieved with source_id, record_id, provenance_url | ✅ Pass (integration tests) |
| PB-4 | Import isolation | No Level 0 imports | AST scan: 0 violations | ✅ Pass (test_import_isolation.py) |
| PB-5 | Checkpoint safety *(conditional)* | Static state scan plus full persisted-surface inspection when checkpointing and framework hooks are enabled | Full inspection auto-waived when installed framework lacks ingress hooks | ✅ Pass / Auto-waived |
| PB-6 | Invoke execution order | `__call__()`: S-1 trust gate → S-4 `node_start` → S-2 → `execute()` → S-3 → S-4 `node_complete` | Order verified for all 6 nodes; negative S-1 test: ANONYMOUS → ERROR | ✅ Pass (test_pb_invoke_order.py) |
| PB-7 | HITL interrupt propagation | `GraphInterrupt` propagates to LangGraph engine; `hitl_allowed=False` prevents deadlock | Both verified for BriefingNode | ✅ Pass (test_pb7_hitl_interrupt_propagation.py) |

## Business Logic Tests

| TC-ID | Test | Input | Expected Result | Result |
|-------|------|-------|----------------|--------|
| BL-01 | Valid scope with event_id returns success | event_id="EVT-001", change_type="postponement" | SUCCESS, change_scope_json populated | ✅ Pass |
| BL-02 | Empty user_input returns ERROR | user_input="" | ERROR status | ✅ Pass |
| BL-03 | Missing event_id and competition_name returns ERROR | Neither field provided | ERROR status | ✅ Pass |
| BL-04 | Invalid change_type blocked by S-2 gate | change_type="schedule_approval" | ERROR status (gate violation) | ✅ Pass |
| BL-05 | Mock source returns normalized records | approved_sources=["mock://source"] | Records with source_id, provenance_url | ✅ Pass |
| BL-06 | No approved sources returns partial_result=True | approved_sources=[] | partial_result=True, empty history | ✅ Pass |
| BL-07 | History evidence produces contractual-impact references | postponement history record present | ≥1 impact with clause_ref, obligation_type | ✅ Pass |
| BL-08 | No history returns uncertain placeholder (not error) | schedule_history=[] | uncertainty_flag=True placeholder | ✅ Pass |
| BL-09 | Postponement returns Participants and Ticketholders groups | change_type="postponement" | Both group_names present in stakeholder_reqs | ✅ Pass |
| BL-10 | HITL disabled: briefing_draft set without interrupt | hitl_allowed=False | briefing_draft non-empty, review_outcome="approved" | ✅ Pass |
| BL-11 | HITL resume with approved feedback | hitl_feedback="approve" | review_outcome="approved", original draft retained | ✅ Pass |
| BL-11b | HITL resume with corrected feedback | hitl_feedback={action="correct", corrected_output=...} | review_outcome="corrected", corrected text used | ✅ Pass |
| BL-11c | HITL resume with rejected feedback | hitl_feedback="reject" | review_outcome="rejected", status=CANCELLED | ✅ Pass |
| BL-12 | Approved briefing returns formatted output with disclaimer | review_outcome="approved" | formatted_output contains "DECISION SUPPORT ONLY" | ✅ Pass |

## Integration Tests

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| INT-01 | Full pipeline with mock source returns formatted briefing | Output contains decision-support disclaimer | ✅ Pass |
| INT-02 | Pipeline with no approved sources returns partial output | partial_result=True or informative notice | ✅ Pass |
| INT-03 | Empty input rejected at pre-process boundary (not inner graph) | ERROR status returned early | ✅ Pass |
| INT-04 | Graph name matches manifest | graph.name == "svc-c2-072" | ✅ Pass |
| INT-05 | Graph state_schema is project State | graph.state_schema is State | ✅ Pass |

## Test Execution Summary
- Execution date: 2026-08-18
- Total tests: 47
- Pass: 46 / Fail: 0 / Skip: 1
- Skipped: PB-5 full checkpoint-surface assertion (installed AgentCore lacks both ingress-protection hooks)
- Coverage: Not measured in this run
- Command: `python -m pytest tests -q --tb=short`
