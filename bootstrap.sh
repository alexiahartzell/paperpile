#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$REPO_DIR/zotero-mcp/.venv"
FORCE=false

if [[ "${1:-}" == "--force" ]]; then
    FORCE=true
fi

echo "Setting up paperpile..."

# 1. Check Python 3
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Please install Python 3 first."
    exit 1
fi
echo "✓ Python 3 found: $(python3 --version)"

# 2. Create venv
if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
else
    echo "✓ Virtual environment exists"
fi

# 3. Install deps
echo "Installing dependencies..."
"$VENV_DIR/bin/pip" install -q -r "$REPO_DIR/zotero-mcp/requirements.txt"
echo "✓ Dependencies installed"

# 4. Generate config.json (never overwritten by --force)
CONFIG="$REPO_DIR/zotero-mcp/config.json"
if [[ ! -f "$CONFIG" ]]; then
    cat > "$CONFIG" <<CONF
{
  "zotero_user_id": "",
  "library_type": "user",
  "papers_queue": "$REPO_DIR/queue",
  "papers_library": "$REPO_DIR/library"
}
CONF
    echo "✓ Created zotero-mcp/config.json (needs credentials — Claude will help)"
else
    echo "✓ zotero-mcp/config.json exists (not overwriting)"
fi

# 5. Generate .mcp.json
MCP="$REPO_DIR/.mcp.json"
if [[ ! -f "$MCP" ]] || [[ "$FORCE" == true ]]; then
    cat > "$MCP" <<MCP_JSON
{
  "mcpServers": {
    "zotero": {
      "type": "stdio",
      "command": "$VENV_DIR/bin/python3",
      "args": ["$REPO_DIR/zotero-mcp/server.py"],
      "env": { "ZOTERO_API_KEY": "" }
    }
  }
}
MCP_JSON
    echo "✓ Created .mcp.json"
else
    echo "✓ .mcp.json exists (use --force to regenerate)"
fi

# 6. Generate .claude/settings.local.json
SETTINGS_DIR="$REPO_DIR/.claude"
SETTINGS="$SETTINGS_DIR/settings.local.json"
if [[ ! -f "$SETTINGS" ]] || [[ "$FORCE" == true ]]; then
    mkdir -p "$SETTINGS_DIR"
    cat > "$SETTINGS" <<SETTINGS_JSON
{
  "permissions": {
    "allow": ["mcp__zotero__*"]
  },
  "enableAllProjectMcpServers": true,
  "enabledMcpjsonServers": ["zotero"]
}
SETTINGS_JSON
    echo "✓ Created .claude/settings.local.json"
else
    echo "✓ .claude/settings.local.json exists (use --force to regenerate)"
fi

echo ""
echo "Bootstrap complete. Run 'claude' to finish configuration."
