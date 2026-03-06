"""Tests for the improver module."""

import json

from cc_improve.improver.propose import get_top_patterns


def test_get_top_patterns_empty(db_conn):
    patterns = get_top_patterns(db_conn)
    assert patterns == []


def test_get_top_patterns_filters_low_count(db_conn):
    db_conn.execute("""
        INSERT INTO failure_patterns (failure_type, root_cause_cluster, occurrence_count, severity_mode, first_seen, last_seen)
        VALUES ('has_tool_misuse', 'redundant reads', 2, 'medium', '2026-03-01', '2026-03-01')
    """)
    db_conn.commit()

    # Default min_occurrences=3, so this should be filtered out
    patterns = get_top_patterns(db_conn)
    assert len(patterns) == 0


def test_get_top_patterns_ranked_by_score(db_conn):
    db_conn.execute("""
        INSERT INTO failure_patterns (failure_type, root_cause_cluster, occurrence_count, severity_mode, first_seen, last_seen)
        VALUES ('has_tool_misuse', 'redundant reads', 5, 'low', '2026-03-01', '2026-03-01')
    """)
    db_conn.execute("""
        INSERT INTO failure_patterns (failure_type, root_cause_cluster, occurrence_count, severity_mode, first_seen, last_seen)
        VALUES ('is_cyclical', 'loop on error', 3, 'high', '2026-03-01', '2026-03-01')
    """)
    db_conn.commit()

    patterns = get_top_patterns(db_conn, min_occurrences=3, top_n=5)
    assert len(patterns) == 2
    # is_cyclical (3 * 3 = 9) should rank above has_tool_misuse (5 * 1 = 5)
    assert patterns[0]["failure_type"] == "is_cyclical"
