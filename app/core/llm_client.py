"""
Thin wrapper around the Groq SDK.

Centralizes model name, temperature, and the two call shapes the rest of the
system needs:
  - chat_json:        JSON-mode call -> parsed dict (used by Planner)
  - chat_with_tools:  native function-calling call (used by Executor/ToolManager)
  - chat_text:        plain text completion (used for section generation)

Keeping this isolated means Planner/Executor never touch the Groq SDK directly,
so swapping providers later only means editing this one file.
"""
import json
from typing import Any, Optional

from groq import Groq

from app.core.config import settings

_client: Optional[Groq] = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=settings.groq_api_key)
    return _client


def chat_json(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    """Call the LLM in JSON mode and return the parsed dict."""
    client = _get_client()
    response = client.chat.completions.create(
        model=settings.groq_model,
        temperature=settings.llm_temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    raw = response.choices[0].message.content
    return json.loads(raw)


def chat_text(system_prompt: str, user_prompt: str) -> str:
    """Plain text completion, used for generating a single document section."""
    client = _get_client()
    response = client.chat.completions.create(
        model=settings.groq_model,
        temperature=settings.llm_temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content.strip()


def chat_with_tools(
    system_prompt: str,
    user_prompt: str,
    tools: list[dict],
) -> Any:
    """
    Native Groq function-calling call. Returns the raw message object so the
    caller (ToolManager/Executor) can inspect tool_calls and dispatch them.
    """
    client = _get_client()
    response = client.chat.completions.create(
        model=settings.groq_model,
        temperature=settings.llm_temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        tools=tools,
        tool_choice="auto",
    )
    return response.choices[0].message
