"""Tests for the JSONL parser."""

from catharsis.collector.parser import parse_jsonl


def test_parse_basic_session(sample_jsonl):
    result = parse_jsonl(sample_jsonl)

    assert result is not None
    assert result.session_id == "test-session-001"
    assert result.model == "claude-opus-4-6"
    assert result.git_branch == "main"
    assert result.cc_version == "2.1.0"


def test_deduplicates_streaming_messages(sample_jsonl):
    result = parse_jsonl(sample_jsonl)

    # msg_001 appears twice in JSONL but should be deduped to one
    assistant_msgs = [m for m in result.messages if m.role == "assistant"]
    msg_001_count = sum(
        1 for m in result.messages
        if m.role == "assistant" and any(
            tu.get("id") == "toolu_001" for tu in m.tool_uses
        )
    )
    # The deduplicated version should have the tool_use
    assert msg_001_count == 1


def test_extracts_tool_uses(sample_jsonl):
    result = parse_jsonl(sample_jsonl)

    all_tool_uses = []
    for msg in result.messages:
        all_tool_uses.extend(msg.tool_uses)

    tool_names = [tu["name"] for tu in all_tool_uses]
    assert "Read" in tool_names
    assert "Edit" in tool_names
    assert "Bash" in tool_names


def test_extracts_tool_results(sample_jsonl):
    result = parse_jsonl(sample_jsonl)

    tool_result_msgs = [m for m in result.messages if m.is_tool_result]
    assert len(tool_result_msgs) == 2  # Read result + Edit result


def test_extracts_tokens(sample_jsonl):
    result = parse_jsonl(sample_jsonl)

    assistant_msgs = [m for m in result.messages if m.role == "assistant"]
    total_output = sum(m.output_tokens for m in assistant_msgs)
    assert total_output == 160  # 50 + 80 + 30 from fixture


def test_handles_timestamps(sample_jsonl):
    result = parse_jsonl(sample_jsonl)

    assert result.start_time == "2026-03-01T10:00:00Z"
    assert result.end_time == "2026-03-01T10:00:15Z"


def test_nonexistent_file(tmp_path):
    result = parse_jsonl(tmp_path / "nonexistent.jsonl")
    assert result is None


def test_empty_file(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    result = parse_jsonl(empty)
    assert result is None


def test_malformed_lines(tmp_path):
    """Malformed lines should be skipped gracefully."""
    path = tmp_path / "bad.jsonl"
    path.write_text('{"type":"user","sessionId":"s1","message":{"role":"user","content":"hi"}}\n{bad json\n')
    result = parse_jsonl(path)
    assert result is not None
    assert len(result.messages) == 1
