"""JSONL parser for Claude Code session transcripts.

Handles streaming message deduplication (assistant messages with same message.id
are streamed incrementally — we keep only the last occurrence).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ParsedMessage:
    """A single deduplicated message from a session."""
    index: int
    uuid: str | None
    parent_uuid: str | None
    role: str
    content_text: str
    thinking_text: str
    timestamp: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    model: str | None = None
    is_tool_result: bool = False
    tool_uses: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ParsedSession:
    """All parsed data from a single session JSONL."""
    session_id: str
    messages: list[ParsedMessage]
    model: str | None = None
    git_branch: str | None = None
    cc_version: str | None = None
    start_time: str | None = None
    end_time: str | None = None


def _extract_text(content: Any) -> str:
    """Extract text content from message content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return ""


def _extract_thinking(content: Any) -> str:
    """Extract thinking content from message content blocks."""
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "thinking":
            parts.append(block.get("thinking", ""))
    return "\n".join(p for p in parts if p)


def _extract_tool_uses(content: Any) -> list[dict[str, Any]]:
    """Extract tool_use blocks from message content."""
    if not isinstance(content, list):
        return []
    return [
        block for block in content
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]


def _extract_tool_results(content: Any) -> list[dict[str, Any]]:
    """Extract tool_result blocks from message content."""
    if not isinstance(content, list):
        return []
    return [
        block for block in content
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]


def _get_usage(msg_data: dict[str, Any]) -> tuple[int, int, int, int]:
    """Extract token usage from a message."""
    usage = msg_data.get("usage", {})
    return (
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
        usage.get("cache_read_input_tokens", 0),
        usage.get("cache_creation_input_tokens", 0),
    )


def parse_jsonl(path: Path) -> ParsedSession | None:
    """Parse a JSONL session file into structured data.

    Handles:
    - Streaming message dedup (same message.id -> keep last)
    - Tool result matching
    - Malformed line skipping
    """
    if not path.exists():
        return None

    lines: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                lines.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSONL line %d in %s", line_num, path)

    if not lines:
        return None

    session_id: str | None = None
    git_branch: str | None = None
    cc_version: str | None = None

    # First pass: extract session metadata and deduplicate assistant messages
    # Assistant messages stream incrementally — multiple JSONL lines share the
    # same message.id. We keep only the last line per message.id.
    assistant_by_msg_id: dict[str, tuple[int, dict[str, Any]]] = {}
    ordered_lines: list[tuple[int, dict[str, Any]]] = []

    for idx, raw in enumerate(lines):
        msg_type = raw.get("type")

        # Skip non-message types
        if msg_type in ("file-history-snapshot", "progress"):
            continue

        # Extract session metadata from any line that has it
        if not session_id:
            session_id = raw.get("sessionId") or raw.get("session_id")
        if not git_branch:
            git_branch = raw.get("gitBranch")
        if not cc_version:
            cc_version = raw.get("version")

        if msg_type == "assistant":
            msg_data = raw.get("message", {})
            msg_id = msg_data.get("id")
            if msg_id:
                assistant_by_msg_id[msg_id] = (idx, raw)
            else:
                ordered_lines.append((idx, raw))
        elif msg_type in ("user", "system"):
            ordered_lines.append((idx, raw))

    # Add deduplicated assistant messages (keep last per message.id)
    for msg_id, (idx, raw) in assistant_by_msg_id.items():
        ordered_lines.append((idx, raw))

    # Sort by original line order
    ordered_lines.sort(key=lambda x: x[0])

    if not session_id:
        session_id = path.stem

    # Second pass: build ParsedMessage list
    messages: list[ParsedMessage] = []
    for msg_idx, (_, raw) in enumerate(ordered_lines):
        msg_type = raw.get("type", "")
        msg_data = raw.get("message", {})
        content = msg_data.get("content") if isinstance(msg_data, dict) else None

        role = msg_type if msg_type in ("user", "assistant", "system") else "unknown"

        # Check if this is a tool result message
        is_tr = False
        tool_results: list[dict[str, Any]] = []
        if role == "user" and content:
            tool_results = _extract_tool_results(content)
            if tool_results:
                is_tr = True

        tool_uses: list[dict[str, Any]] = []
        if role == "assistant" and content:
            tool_uses = _extract_tool_uses(content)

        input_t, output_t, cache_read, cache_create = (0, 0, 0, 0)
        if isinstance(msg_data, dict):
            input_t, output_t, cache_read, cache_create = _get_usage(msg_data)

        messages.append(ParsedMessage(
            index=msg_idx,
            uuid=raw.get("uuid"),
            parent_uuid=raw.get("parentUuid"),
            role=role,
            content_text=_extract_text(content) if content else "",
            thinking_text=_extract_thinking(content) if content else "",
            timestamp=raw.get("timestamp"),
            input_tokens=input_t,
            output_tokens=output_t,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_create,
            model=msg_data.get("model") if isinstance(msg_data, dict) else None,
            is_tool_result=is_tr,
            tool_uses=tool_uses,
            tool_results=tool_results,
        ))

    model = None
    start_time = None
    end_time = None
    for m in messages:
        if m.model:
            model = m.model
        if m.timestamp:
            if not start_time:
                start_time = m.timestamp
            end_time = m.timestamp

    return ParsedSession(
        session_id=session_id,
        messages=messages,
        model=model,
        git_branch=git_branch,
        cc_version=cc_version,
        start_time=start_time,
        end_time=end_time,
    )
