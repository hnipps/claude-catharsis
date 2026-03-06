"""Path constants for Claude Catharsis."""

from pathlib import Path

BASE_DIR = Path.home() / ".claude-analysis"
DB_PATH = BASE_DIR / "conversations.db"
CONFIG_PATH = BASE_DIR / "config.yaml"
ARCHIVE_DIR = BASE_DIR / "archive"
REPORTS_DIR = BASE_DIR / "reports"
PROPOSALS_DIR = BASE_DIR / "proposals"
LOGS_DIR = BASE_DIR / "logs"
PROMPTS_DIR = Path(__file__).parent / "prompts"

CLAUDE_DIR = Path.home() / ".claude"
CLAUDE_PROJECTS_DIR = CLAUDE_DIR / "projects"


def decode_project_path(encoded: str) -> str:
    """Decode an encoded project directory name back to a path.

    Claude encodes paths like: -Users-harry-nicholls-repos-myproject
    This maps back to: /Users/harry/nicholls/repos/myproject
    """
    if encoded.startswith("-"):
        return "/" + encoded[1:].replace("-", "/")
    return encoded.replace("-", "/")


def load_prompt(name: str) -> str:
    """Load a prompt template by name (e.g. 'analyze' or 'improve')."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def prompt_version(template: str) -> str:
    """SHA-256 hash of a prompt template (before substitution)."""
    import hashlib
    return hashlib.sha256(template.encode("utf-8")).hexdigest()[:12]


def ensure_dirs() -> None:
    """Create all required directories."""
    for d in [BASE_DIR, ARCHIVE_DIR, REPORTS_DIR, PROPOSALS_DIR, LOGS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
