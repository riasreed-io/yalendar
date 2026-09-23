"""Builds the Yalendar agent and runs one message through it.

Import-safe with no credentials present: the model and Agent are built lazily
inside run_agent, so `python -c "import yale_today.agent.agent"` works offline
and the test suite can import the tools without an API key.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ..config import ROOT
from .models import AgentReply, ToolCallRecord
from .tools import ALL_TOOLS

PROMPT_PATH = ROOT / "prompts" / "prompt.md"
AUDIT_PATH = ROOT / "output" / "audit_trail.json"
RESULT_PREVIEW_CHARS = 400

DEFAULT_MODEL = "gpt-5"


def _load_env() -> None:
    """Read .env from the project root and one level up, without overriding
    anything already exported in the shell."""
    for path in (ROOT / ".env", ROOT.parent / ".env"):
        if path.is_file():
            load_dotenv(path, override=False)


def load_prompt() -> str:
    """The system prompt lives on disk so it can be edited without a deploy."""
    if not PROMPT_PATH.is_file():
        raise FileNotFoundError(f"System prompt not found at {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def build_agent(*, web_search: bool = True):
    """Construct the Agent. Requires an API key; raises a clear error without one."""
    from pydantic_ai import Agent
    from pydantic_ai.capabilities import WebSearch
    from pydantic_ai.models.openai import OpenAIResponsesModel
    from pydantic_ai.providers.openai import OpenAIProvider

    _load_env()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in. "
            "The key is read from the environment and never logged."
        )

    provider_kwargs: dict[str, Any] = {"api_key": api_key}
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    if base_url:
        provider_kwargs["base_url"] = base_url

    # OpenAIResponsesModel, not OpenAIChatModel: the chat model rejects
    # WebSearch with "WebSearchTool is not supported with OpenAIChatModel".
    model = OpenAIResponsesModel(
        os.environ.get("YALENDAR_MODEL", DEFAULT_MODEL),
        provider=OpenAIProvider(**provider_kwargs),
    )

    # Native tools are capabilities in pydantic-ai 2.x. There is no
    # builtin_tools parameter.
    capabilities = [WebSearch(id="web_search")] if web_search else []
    return Agent(
        model,
        instructions=load_prompt(),
        tools=list(ALL_TOOLS),
        capabilities=capabilities,
    )


def _preview(value: Any) -> str:
    try:
        text = value if isinstance(value, str) else json.dumps(value, default=str)
    except (TypeError, ValueError):
        text = str(value)
    text = " ".join(text.split())
    if len(text) > RESULT_PREVIEW_CHARS:
        return text[:RESULT_PREVIEW_CHARS] + "..."
    return text


def _collect_tool_calls(messages: list) -> list[ToolCallRecord]:
    """Pull tool calls, and their returns, out of the run's message history."""
    from pydantic_ai.messages import NativeToolCallPart, ToolCallPart

    try:
        from pydantic_ai.messages import ToolReturnPart
    except ImportError:  # pragma: no cover - defensive across point releases
        ToolReturnPart = ()  # type: ignore[assignment]

    returns: dict[str, Any] = {}
    for message in messages:
        for part in getattr(message, "parts", []):
            if ToolReturnPart and isinstance(part, ToolReturnPart):
                key = getattr(part, "tool_call_id", None)
                if key:
                    returns[key] = getattr(part, "content", "")

    calls: list[ToolCallRecord] = []
    for message in messages:
        for part in getattr(message, "parts", []):
            if not isinstance(part, (ToolCallPart, NativeToolCallPart)):
                continue
            args = part.args
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {"raw": args}
            call_id = getattr(part, "tool_call_id", None)
            calls.append(
                ToolCallRecord(
                    name=part.tool_name,
                    args=args if isinstance(args, dict) else {"value": args},
                    result_preview=_preview(returns.get(call_id, "")),
                    native=isinstance(part, NativeToolCallPart),
                )
            )
    return calls


def _stop_reason(messages: list) -> str:
    for message in reversed(messages):
        reason = getattr(message, "finish_reason", None)
        if reason:
            return str(reason)
    return "unknown"


def append_audit(entry: dict) -> None:
    """Append one run to output/audit_trail.json. Never overwrites history."""
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: list = []
    if AUDIT_PATH.is_file():
        try:
            loaded = json.loads(AUDIT_PATH.read_text(encoding="utf-8") or "[]")
            if isinstance(loaded, list):
                existing = loaded
            else:
                existing = [loaded]
        except ValueError:
            # A corrupt file must not lose the run or crash the request.
            backup = AUDIT_PATH.with_suffix(".corrupt.json")
            AUDIT_PATH.replace(backup)
    existing.append(entry)
    AUDIT_PATH.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")


def run_agent(message: str, *, web_search: bool = True) -> dict:
    """Run one message and return {"reply", "tools_used"}.

    Every run is appended to output/audit_trail.json with the tool calls,
    their arguments, trimmed results, and the stop reason.
    """
    started = datetime.now(timezone.utc)
    agent = build_agent(web_search=web_search)
    result = agent.run_sync(message)
    messages = result.all_messages()
    calls = _collect_tool_calls(messages)

    append_audit(
        {
            "time": started.isoformat(),
            "message": message,
            "tool_calls": [call.model_dump() for call in calls],
            "stop_reason": _stop_reason(messages),
        }
    )

    reply = AgentReply(
        reply=result.output,
        tools_used=list(dict.fromkeys(call.name for call in calls)),
    )
    return reply.model_dump()
