"""FastAPI entry point for the Schedule Change Stakeholder Briefing Agent."""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from framework.secrets.context import bound_secrets
from framework.utils.config_loader import load_config
from shared.secrets import factory as secrets_factory
from shared.secrets.chained_provider import ChainedSecretProvider
from shared.secrets.env_provider import EnvProvider
from src.graph.graph import Graph

app = FastAPI(title="SVC-C2-072 Sports Competition Schedule Change Stakeholder Briefing Agent")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
_config = load_config(str(_CONFIG_PATH)) if _CONFIG_PATH.exists() else {}

_namespace = "agent1000"
_domain_secrets_provider = secrets_factory(namespace=_namespace, agent_name="SVC-C2-072")
_secrets_provider = ChainedSecretProvider(
    EnvProvider(namespace=_namespace, agent_name="SVC-C2-072"),
    _domain_secrets_provider,
)
_llm: None = None
_config["llm"] = _llm

agent = Graph(config=_config)
_hitl_enabled = agent.config.get("hitl", {}).get("enabled", False)
_needs_checkpointer = agent.config.get("memory_enabled") or _hitl_enabled
agent.compile(checkpointer=MemorySaver() if _needs_checkpointer else None)
agent.provision_secrets(_secrets_provider)


class InvokeRequest(BaseModel):
    input: str
    session_id: str = ""
    hitl_allowed: bool = True
    input_context: dict[str, Any] = Field(default_factory=dict)


def _bearer_matches(supplied: str, expected: str) -> bool:
    """Compare a supplied bearer value in constant time."""
    return secrets.compare_digest(supplied.encode(), f"Bearer {expected}".encode())


def _resolve_standalone_trust(
    current: TrustLevel,
    authorization: str,
    invoke_auth_token: str | None,
    internal_runner_token: str | None,
) -> TrustLevel:
    """Authenticate callers without allowing an external token to grant INTERNAL trust."""
    if current is not TrustLevel.ANONYMOUS:
        return current
    if internal_runner_token and _bearer_matches(authorization, internal_runner_token):
        return TrustLevel.INTERNAL
    if invoke_auth_token and _bearer_matches(authorization, invoke_auth_token):
        return TrustLevel.VERIFIED_EXTERNAL
    if internal_runner_token or invoke_auth_token:
        raise HTTPException(status_code=401, detail="Token is invalid or expired.")
    return TrustLevel.ANONYMOUS


@app.post("/invoke")
async def invoke(req: InvokeRequest, request: Request) -> dict[str, Any]:
    trust = _resolve_standalone_trust(
        getattr(request.state, "trust_level", TrustLevel.ANONYMOUS),
        request.headers.get("authorization", ""),
        os.environ.get("INVOKE_AUTH_TOKEN"),
        os.environ.get("STG_INTERNAL_RUNNER_TOKEN"),
    )
    merged_context = {"raw": req.input, **req.input_context}
    with bound_secrets(agent._secrets_provider):
        ctx = InvocationContext(
            session_id=req.session_id or str(uuid4()),
            caller_trust_level=trust,
            caller_id=getattr(request.state, "caller_id", ""),
            hitl_allowed=req.hitl_allowed,
        )
        return cast(dict[str, Any], agent.invoke(req.input, ctx=ctx, input_context=merged_context))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "svc-c2-072"}
