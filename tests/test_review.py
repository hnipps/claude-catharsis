"""Tests for the review module."""

from datetime import datetime, timezone

from catharsis.reviewer.interactive import get_pending_proposals, _reject_proposal


def test_get_pending_proposals_empty(db_conn):
    proposals = get_pending_proposals(db_conn)
    assert proposals == []


def test_get_pending_proposals(db_conn):
    db_conn.execute("""
        INSERT INTO proposals (title, target_file, change_type, proposed_content, status, created_at)
        VALUES ('Test proposal', 'CLAUDE.md', 'addition', 'new rule', 'pending', '2026-03-01')
    """)
    db_conn.commit()

    proposals = get_pending_proposals(db_conn)
    assert len(proposals) == 1
    assert proposals[0]["title"] == "Test proposal"


def test_get_pending_proposals_excludes_reviewed(db_conn):
    db_conn.execute("""
        INSERT INTO proposals (title, target_file, change_type, proposed_content, status, created_at)
        VALUES ('Accepted', 'CLAUDE.md', 'addition', 'rule 1', 'accepted', '2026-03-01')
    """)
    db_conn.execute("""
        INSERT INTO proposals (title, target_file, change_type, proposed_content, status, created_at)
        VALUES ('Pending', 'CLAUDE.md', 'addition', 'rule 2', 'pending', '2026-03-01')
    """)
    db_conn.commit()

    proposals = get_pending_proposals(db_conn)
    assert len(proposals) == 1
    assert proposals[0]["title"] == "Pending"


def test_reject_proposal(db_conn):
    db_conn.execute("""
        INSERT INTO proposals (title, target_file, change_type, proposed_content, status, created_at)
        VALUES ('Test', 'CLAUDE.md', 'addition', 'content', 'pending', '2026-03-01')
    """)
    db_conn.commit()

    row = db_conn.execute("SELECT id FROM proposals").fetchone()
    _reject_proposal(db_conn, row["id"], "Not relevant")

    updated = db_conn.execute("SELECT * FROM proposals WHERE id = ?", (row["id"],)).fetchone()
    assert updated["status"] == "rejected"
    assert updated["rejection_reason"] == "Not relevant"
