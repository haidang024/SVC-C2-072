# SVC-C2-072 — Sports Competition Schedule Change Stakeholder Briefing Agent

> **Category**: Cat 2 (fixed multi-step domain workflow)
> **Industry**: Services

## Overview

Given a schedule-change scope (an event ID or competition name, a change type such as
postponement or venue change, and a set of operator-approved source identifiers), this template
retrieves the relevant change history from those approved sources, maps the evidence to
contractual-impact references, identifies the stakeholder groups that need to be told and what
they need to be told, and drafts a cited stakeholder briefing. The draft is held for mandatory
human review before it is returned. It does not decide whether a schedule change is approved,
does not modify a schedule or a contract, and does not send anything to a stakeholder — the
briefing is decision support for a human reviewer, and everything downstream of the interrupt
happens outside this agent. When a source in the approved list cannot be reached, the pipeline
keeps going with what it has and flags the gap in the briefing rather than failing the whole
request or silently treating "not retrieved" as "nothing happened".

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Without it, start-up fails immediately (see *Behaviour without the platform* below). Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | >=3.11 |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run **only** on AGENTIC STAR. There is no fallback or degraded
mode. If the platform is unreachable or the SDK version does not match, the agent raises
`PlatformRequired` during graph compile / start-up preflight rather than starting in a partially
working state. This is intentional — a half-running agent is worse than one that refuses to start.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Tests run without a platform connection. Running the agent itself does not.

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent configuration
docs/         design and test specifications
```

See `docs/` for the design specification and test specification.

### Architecture

```
START → initialize → pre_process → main → post_process → finalize → END
                                     └─ history_retrieval
                                        → contract_impact
                                        → stakeholder_reqs
                                        → briefing ──[interrupt()]──► human review
```

`pre_process` validates and normalises the change scope and the approved-source list at
`VERIFIED_EXTERNAL` trust; the four inner nodes run at `ANONYMOUS` because trust was already
checked at that boundary. `briefing` calls `interrupt()` once the draft is assembled, so the
graph pauses for a human reviewer before `post_process` formats the final output; the caller can
set `hitl_allowed=false` only for controlled non-interactive runs, in which case the draft is
returned directly with `review_outcome="approved"`.

## Customising

1. Adjust `config/config.yaml` for your own environment — retry and timeout budgets, whether
   memory/checkpointing is enabled, and the HITL policy (`hitl.enabled`, `hitl.max_hitl`).
2. Replace the mock schedule-history source behind `history_retrieval` with your own operator
   systems, and update the approved-source allowlist and `SCHEDULE_SOURCE_MOCK_API_KEY` secret
   accordingly.
3. Review `src/nodes/contract_impact_node.py` and `src/nodes/stakeholder_reqs_node.py` for the
   domain rules mapping a change type to contractual-impact categories and stakeholder groups —
   these are placeholders for your own policy tables.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.
