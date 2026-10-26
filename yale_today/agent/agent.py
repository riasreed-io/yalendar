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

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
from .models import AgentReply, ToolCallRecord
from .tools import ALL_TOOLS

PROMPT_PATH = ROOT / "prompts" / "prompt.md"
AUDIT_PATH = ROOT / "output" / "audit_trail.json"
RESULT_PREVIEW_CHARS = 400

# MGT 409 issues a Portkey gateway key, not a raw OpenAI one, and the course
# budget assumes gpt-6-luna. Following the class stack means the agent runs on
# the key Rias already has instead of waiting on a personal OpenAI account.
DEFAULT_MODEL = "gpt-6-luna"
PORTKEY_BASE_URL = os.environ.get(
    "PORTKEY_BASE_URL", "https://api.portkey.ai/v1").rstrip("/")

# Ceilings for a single question. A campus-events answer is one or two tool
# calls and a short paragraph; anything beyond this is a loop or an attack,
# and without a ceiling either one bills until someone notices.
MAX_REQUESTS = 6          # model round-trips
MAX_TOOL_CALLS = 6
MAX_TOTAL_TOKENS = 40_000
MAX_COST_USD = "0.25"     # hard stop per question, whatever the model costs

# The native web_search tool is billed per call on top of tokens ($10 per
# 1,000 calls at current pricing, i.e. about as much as the rest of the run).
# Every event Yalendar can answer about is already in the local database, so
# it is off unless someone deliberately asks for it.
WEB_SEARCH_DEFAULT = os.environ.get("YALENDAR_WEB_SEARCH") == "1"


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


# Models pydantic-ai has no price table for -- the MGT 409 gateway's own.
# It cannot enforce a cost_limit on these and only emits a warning, so a
# cost_limit here would look like a defence and do nothing.
UNPRICED_MODELS = frozenset({"gpt-6-luna", "gpt-6-astra"})


def usage_limits():
    """Per-question ceilings on requests, tool calls, tokens and spend.

    Dollars are only passed to pydantic-ai when it can actually price the
    model. For the course gateway it cannot, so the binding per-run limit
    is tokens, and dollars are enforced in budget.py against the course
    price table. Leaving an unenforceable cost_limit in place was worse
    than not setting one: the warning is easy to miss and the ceiling
    reads as present in the code.
    """
    from decimal import Decimal

    from pydantic_ai.usage import UsageLimits

    limits: dict = {
        "request_limit": MAX_REQUESTS,
        "tool_calls_limit": MAX_TOOL_CALLS,
        "total_tokens_limit": MAX_TOTAL_TOKENS,
    }
    if os.environ.get("YALENDAR_MODEL", DEFAULT_MODEL) not in UNPRICED_MODELS:
        limits["cost_limit"] = Decimal(MAX_COST_USD)
    return UsageLimits(**limits)


def credential() -> tuple[str, str]:
    """Which credential is configured: ("portkey"|"openai"|"", key).

    Portkey first, because that is what the course hands out. Falling back
    to a raw OpenAI key keeps the app usable by anyone who clones it.
    The value is returned, never printed or logged.
    """
    _load_env()
    key = os.environ.get("PORTKEY_API_KEY", "").strip()
    if key:
        return "portkey", key
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return "openai", key
    return "", ""


def build_agent(*, web_search: bool = WEB_SEARCH_DEFAULT):
    """Construct the Agent. Requires an API key; raises a clear error without one."""
    from pydantic_ai import Agent
    from pydantic_ai.capabilities import WebSearch
    from pydantic_ai.models.openai import OpenAIResponsesModel
    from pydantic_ai.providers.openai import OpenAIProvider

    kind, api_key = credential()
    if not kind:
        raise RuntimeError(
            "No model credential. Set PORTKEY_API_KEY (the MGT 409 gateway "
            "key) or OPENAI_API_KEY in .env. Either is read from the "
            "environment and never logged."
        )

    if kind == "portkey":
        # The gateway speaks the OpenAI API, so the only differences are the
        # base URL and the provider header. It rejects the class virtual key,
        # so that is deliberately not sent.
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=PORTKEY_BASE_URL,
            default_headers={"x-portkey-provider": "openai"},
        )
        provider = OpenAIProvider(openai_client=client)
    else:
        provider_kwargs: dict[str, Any] = {"api_key": api_key}
        base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
        if base_url:
            provider_kwargs["base_url"] = base_url
        provider = OpenAIProvider(**provider_kwargs)

    # OpenAIResponsesModel, not OpenAIChatModel: the chat model rejects
    # WebSearch with "WebSearchTool is not supported with OpenAIChatModel".
    model = OpenAIResponsesModel(
        os.environ.get("YALENDAR_MODEL", DEFAULT_MODEL),
        provider=provider,
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


def _usage(result) -> dict:
    """Real token counts for the run, so cost is measured and not guessed.

    `usage` is a property on pydantic-ai 2.48 and was a method on earlier
    releases. Calling it unconditionally raised TypeError straight into a
    bare `except`, so every run recorded {} -- the audit trail looked fine
    and every dollar-denominated cap was quietly billing zero. Accept both
    shapes, and let a genuinely unexpected failure be visible rather than
    swallowed into an empty dict.
    """
    usage = getattr(result, "usage", None)
    if callable(usage):
        usage = usage()
    if usage is None:
        return {}
    get = lambda name: getattr(usage, name, None)  # noqa: E731
    return {
        k: v
        for k, v in {
            "requests": get("requests"),
            "input_tokens": get("input_tokens"),
            "cache_read_tokens": get("cache_read_tokens"),
            "cache_write_tokens": get("cache_write_tokens"),
            "output_tokens": get("output_tokens"),
            "tool_calls": get("tool_calls"),
            "total_tokens": get("total_tokens"),
        }.items()
        if v is not None
    }


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


def run_agent(message: str, *, web_search: bool = WEB_SEARCH_DEFAULT) -> dict:
    """Run one message and return {"reply", "tools_used"}.

    Every run is appended to output/audit_trail.json with the tool calls,
    their arguments, trimmed results, and the stop reason.
    """
    started = datetime.now(timezone.utc)
    agent = build_agent(web_search=web_search)
    result = agent.run_sync(message, usage_limits=usage_limits())
    messages = result.all_messages()
    calls = _collect_tool_calls(messages)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    usage = _usage(result)

    append_audit(
        {
            "time": started.isoformat(),
            "message": message,
            "model": os.environ.get("YALENDAR_MODEL", DEFAULT_MODEL),
            "web_search": web_search,
            "seconds": round(elapsed, 2),
            "usage": usage,
            "tool_calls": [call.model_dump() for call in calls],
            "stop_reason": _stop_reason(messages),
        }
    )

    reply = AgentReply(
        reply=result.output,
        tools_used=list(dict.fromkeys(call.name for call in calls)),
        usage=usage,
    )
    return reply.model_dump()
