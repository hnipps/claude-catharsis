#!/usr/bin/env python3
"""SessionEnd hook script for Claude Code.

Install by adding to ~/.claude/settings.json under hooks.SessionEnd:
{
    "type": "command",
    "command": "python /path/to/catharsis/hooks/session_end.py"
}

Fails open — never blocks the user's Claude session.
"""

import sys


def main() -> int:
    try:
        from catharsis.collector.hook import handle_session_end
        handle_session_end()
    except Exception:
        pass  # Fail open
    return 0


if __name__ == "__main__":
    sys.exit(main())
