"""Apply accepted proposals to target files."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def apply_proposal(proposal: dict) -> bool:
    """Apply a proposal's changes to the target file.

    Creates a git commit if in a git repo.
    Returns True if applied successfully.
    """
    target = Path(proposal["target_file"]).expanduser()
    change_type = proposal.get("change_type", "addition")
    proposed = proposal["proposed_content"]
    current = proposal.get("current_content")

    try:
        if change_type == "deletion" and current:
            try:
                content = target.read_text(encoding="utf-8")
                content = content.replace(current, "")
                target.write_text(content, encoding="utf-8")
            except FileNotFoundError:
                pass
        elif change_type == "modification" and current:
            content = target.read_text(encoding="utf-8")
            content = content.replace(current, proposed)
            target.write_text(content, encoding="utf-8")
        else:
            # Addition: append to file (create if needed)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                content = target.read_text(encoding="utf-8")
                if not content.endswith("\n"):
                    content += "\n"
                content += "\n" + proposed + "\n"
                target.write_text(content, encoding="utf-8")
            except FileNotFoundError:
                target.write_text(proposed + "\n", encoding="utf-8")

        # Try to create a git commit
        _try_git_commit(target, proposal)
        return True

    except Exception:
        logger.exception("Failed to apply proposal: %s", proposal.get("title"))
        return False


def _try_git_commit(target: Path, proposal: dict) -> None:
    """Attempt to create a git commit for the change."""
    try:
        # Check if we're in a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, cwd=target.parent,
        )
        if result.returncode != 0:
            return

        title = proposal.get("title", "instruction improvement")
        pattern_type = proposal.get("failure_type", "unknown")

        subprocess.run(
            ["git", "add", str(target)],
            capture_output=True, cwd=target.parent,
        )
        subprocess.run(
            ["git", "commit", "-m",
             f"cc-improve: {title}\n\nAddresses failure pattern: {pattern_type}"],
            capture_output=True, cwd=target.parent,
        )
    except Exception:
        pass  # Git commit is best-effort
