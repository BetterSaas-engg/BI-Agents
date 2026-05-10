"""Thin Anthropic SDK wrapper.

This is the ONLY module that imports the Anthropic SDK. Everything else uses
the functions exported here. This is the seam for swapping models.

Uses python-dotenv to load .env for the API key.
"""

import logging

import anthropic
from dotenv import load_dotenv

from bi_agent.config import AGENT_MODEL, CHEAP_MODEL, PROJECT_ROOT

logger = logging.getLogger(__name__)

# Load .env from project root (contains ANTHROPIC_API_KEY)
load_dotenv(PROJECT_ROOT / ".env")

# Single client instance, reused across calls
_client = anthropic.Anthropic()


def complete(
    prompt: str,
    *,
    system: str = "",
    model: str = CHEAP_MODEL,
    temperature: float = 0.0,
    max_tokens: int = 4096,
) -> str:
    """Make a simple LLM call and return the text response.

    Used for cheap, non-agentic calls (parser, presenter explanation).

    Args:
        prompt: The user message content.
        system: Optional system prompt.
        model: Model ID. Defaults to Haiku for cheap calls.
        temperature: Sampling temperature. Defaults to 0.
        max_tokens: Max tokens in the response.

    Returns:
        The assistant's text response.

    Raises:
        anthropic.APIError: On API failures.
    """
    messages = [{"role": "user", "content": prompt}]

    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system

    logger.debug("LLM call: model=%s, temperature=%s", model, temperature)
    response = _client.messages.create(**kwargs)
    text = response.content[0].text
    logger.debug("LLM response: %d chars, usage=%s", len(text), response.usage)
    return text


def create_tool_use_message(
    *,
    messages: list[dict],
    tools: list[dict],
    system: str = "",
    model: str = AGENT_MODEL,
    temperature: float = 0.0,
    max_tokens: int = 4096,
) -> anthropic.types.Message:
    """Make an LLM call with tools and return the full Message object.

    Used by the SQL agent loop. The caller is responsible for managing the
    conversation history and tool result messages.

    Args:
        messages: Conversation history (user/assistant/tool_result messages).
        tools: Tool definitions in Anthropic SDK format.
        system: System prompt for the agent.
        model: Model ID. Defaults to Sonnet for the SQL agent.
        temperature: Sampling temperature. Defaults to 0 for SQL generation.
        max_tokens: Max tokens in the response.

    Returns:
        The full anthropic Message object (caller inspects content blocks
        for tool_use vs text).

    Raises:
        anthropic.APIError: On API failures.
    """
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
        "tools": tools,
    }
    if system:
        kwargs["system"] = system

    logger.debug(
        "Tool-use call: model=%s, %d tools, %d messages", model, len(tools), len(messages)
    )
    response = _client.messages.create(**kwargs)
    logger.debug(
        "Tool-use response: stop_reason=%s, usage=%s",
        response.stop_reason,
        response.usage,
    )
    return response
