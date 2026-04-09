#!/usr/bin/env bash
# setup-uv.sh — Install uv (Python package manager) for the devcontainer.
# Required by the Serena MCP plugin (uses uvx to launch its server).
# Usage: .devcontainer/setup-uv.sh
set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m ✓\033[0m  %s\n' "$*"; }

command_exists() { command -v "$1" &>/dev/null; }

# ---------------------------------------------------------------------------
# 1. Install uv
# ---------------------------------------------------------------------------
if command_exists uv; then
  ok "uv already installed ($(uv --version))"
else
  info "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ok "uv installed"
fi

# Source env so uv/uvx are on PATH for the rest of this script.
# shellcheck source=/dev/null
source "$HOME/.local/bin/env" 2>/dev/null || true

# ---------------------------------------------------------------------------
# 2. Verify
# ---------------------------------------------------------------------------
info "uv:  $(uv --version)"
info "uvx: $(command -v uvx)"
ok "Setup complete"
