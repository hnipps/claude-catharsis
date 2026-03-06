"""Session aggregation — compute session-level stats from parsed messages."""

from __future__ import annotations

import json
from dataclasses import dataclass

from cc_improve.collector.parser import ParsedSession


@dataclass
class SessionStats:
    """Aggregated statistics for a session."""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    turn_count: int = 0
    message_count: int = 0
    tool_call_count: int = 0
    has_commits: bool = False
    duration_seconds: float | None = None


def compute_stats(session: ParsedSession) -> SessionStats:
    """Compute aggregate stats from a parsed session."""
    stats = SessionStats()
    stats.message_count = len(session.messages)

    user_msg_count = 0
    for msg in session.messages:
        stats.total_input_tokens += msg.input_tokens
        stats.total_output_tokens += msg.output_tokens
        stats.total_cache_read_tokens += msg.cache_read_tokens
        stats.total_cache_creation_tokens += msg.cache_creation_tokens

        if msg.role == "user" and not msg.is_tool_result:
            user_msg_count += 1

        for tu in msg.tool_uses:
            stats.tool_call_count += 1
            name = tu.get("name", "")
            tool_input = tu.get("input", {})

            # Detect git commits
            if name == "Bash":
                cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
                if "git commit" in cmd:
                    stats.has_commits = True

        for tr in msg.tool_results:
            # Tool results are counted as part of the tool call flow
            pass

    stats.turn_count = user_msg_count

    # Duration
    if session.start_time and session.end_time:
        try:
            from datetime import datetime
            start = datetime.fromisoformat(session.start_time.replace("Z", "+00:00"))
            end = datetime.fromisoformat(session.end_time.replace("Z", "+00:00"))
            stats.duration_seconds = (end - start).total_seconds()
        except Exception:
            pass

    return stats
