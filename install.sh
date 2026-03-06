#!/usr/bin/env bash
set -euo pipefail

echo "Installing cc-improve..."

# Create directory structure
mkdir -p ~/.claude-analysis/{archive,reports,proposals,logs}

# Install the package
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pip install -e "$SCRIPT_DIR"

echo ""
echo "Installation complete!"
echo ""
echo "Add the following to your ~/.claude/settings.json under \"hooks\":"
echo ""
cat <<'HOOK_JSON'
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python SCRIPT_DIR/hooks/session_end.py"
          }
        ]
      }
    ]
  }
}
HOOK_JSON

echo ""
echo "(Replace SCRIPT_DIR with: $SCRIPT_DIR)"
echo ""
echo "Quick start:"
echo "  cc-improve collect          # Backfill all existing sessions"
echo "  cc-improve analyze --skip-llm  # Compute deterministic metrics"
echo "  cc-improve status           # View dashboard"
