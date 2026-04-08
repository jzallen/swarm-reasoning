#!/usr/bin/env bash
# setup-gastown.sh — Install and configure Gas Town for a remote dev environment.
# Assumes: Debian/Ubuntu-based container, git, tmux already available.
# Usage: .devcontainer/setup-gastown.sh [--rig-name NAME] [--rig-url URL]
set -euo pipefail

GO_VERSION="1.24.2"
RIG_NAME="${RIG_NAME:-swarm_reasoning}"
RIG_URL="${RIG_URL:-file:///workspaces/swarm-reasoning}"
GT_HQ="${GT_HQ:-$HOME/gt}"

# ---------------------------------------------------------------------------
# Parse flags
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rig-name) RIG_NAME="$2"; shift 2 ;;
    --rig-url)  RIG_URL="$2";  shift 2 ;;
    --hq)       GT_HQ="$2";    shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--rig-name NAME] [--rig-url URL] [--hq PATH]"
      exit 0 ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m ✓\033[0m  %s\n' "$*"; }
fail()  { printf '\033[1;31m ✖\033[0m  %s\n' "$*" >&2; exit 1; }

command_exists() { command -v "$1" &>/dev/null; }

# ---------------------------------------------------------------------------
# 1. Go
# ---------------------------------------------------------------------------
if command_exists go && [[ "$(go version)" == *"go${GO_VERSION}"* ]]; then
  ok "Go ${GO_VERSION} already installed"
else
  info "Installing Go ${GO_VERSION}..."
  curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" -o /tmp/go.tar.gz
  sudo rm -rf /usr/local/go
  sudo tar -C /usr/local -xzf /tmp/go.tar.gz
  rm /tmp/go.tar.gz
  ok "Go ${GO_VERSION} installed"
fi

export PATH="/usr/local/go/bin:$HOME/go/bin:$PATH"

# Persist PATH for future shells if not already present.
for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
  if [[ -f "$rc" ]] && ! grep -q '/usr/local/go/bin' "$rc"; then
    echo 'export PATH="/usr/local/go/bin:$HOME/go/bin:$PATH"' >> "$rc"
  fi
done

# ---------------------------------------------------------------------------
# 2. Dolt
# ---------------------------------------------------------------------------
if command_exists dolt; then
  ok "Dolt already installed ($(dolt version | head -1))"
else
  info "Installing Dolt..."
  curl -fsSL https://github.com/dolthub/dolt/releases/latest/download/install.sh | sudo bash
  ok "Dolt $(dolt version | head -1) installed"
fi

# Configure Dolt identity (required by beads) if not already set.
if ! dolt config --global --get user.name &>/dev/null; then
  GIT_NAME="$(git config --global user.name 2>/dev/null || echo "Dev User")"
  GIT_EMAIL="$(git config --global user.email 2>/dev/null || echo "dev@localhost")"
  dolt config --global --add user.name "$GIT_NAME"
  dolt config --global --add user.email "$GIT_EMAIL"
  ok "Dolt identity set to ${GIT_NAME} <${GIT_EMAIL}>"
fi

# ---------------------------------------------------------------------------
# 3. Gas Town (gt) + Beads (bd) — built from source
# ---------------------------------------------------------------------------
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

build_from_source() {
  local name="$1" repo="$2" binary="$3"
  if command_exists "$binary"; then
    ok "${binary} already installed ($(${binary} version 2>&1 | head -1))"
    return
  fi
  info "Building ${name} from source..."
  git clone --depth 1 "$repo" "${BUILD_DIR}/${name}"
  make -C "${BUILD_DIR}/${name}" build
  # Install all built binaries (gt produces gt, gt-proxy-server, gt-proxy-client).
  find "${BUILD_DIR}/${name}" -maxdepth 1 -type f -executable -name "${binary}*" \
    -exec sudo cp {} /usr/local/bin/ \;
  ok "${name} installed ($(${binary} version 2>&1 | head -1))"
}

build_from_source "gastown" "https://github.com/steveyegge/gastown.git" "gt"
build_from_source "beads"   "https://github.com/steveyegge/beads.git"   "bd"

# ---------------------------------------------------------------------------
# 4. Create HQ workspace
# ---------------------------------------------------------------------------
if [[ -d "$GT_HQ/mayor" ]]; then
  ok "HQ already exists at ${GT_HQ}"
else
  info "Creating HQ at ${GT_HQ}..."
  gt install "$GT_HQ" --shell
  ok "HQ created"

  info "Initializing git..."
  (cd "$GT_HQ" && gt git-init)
  ok "Git initialized"
fi

# ---------------------------------------------------------------------------
# 5. Add rig (idempotent — skip if already registered)
# ---------------------------------------------------------------------------
if [[ -d "${GT_HQ}/${RIG_NAME}" ]]; then
  ok "Rig '${RIG_NAME}' already registered"
else
  info "Adding rig '${RIG_NAME}' from ${RIG_URL}..."
  (cd "$GT_HQ" && gt rig add "$RIG_NAME" "$RIG_URL")
  ok "Rig '${RIG_NAME}' added"
fi

# ---------------------------------------------------------------------------
# 6. Auto-fix and verify
# ---------------------------------------------------------------------------
info "Running doctor --fix..."
(cd "$GT_HQ" && gt doctor --fix --no-start) || true
ok "Setup complete"

echo ""
info "Gas Town is ready at ${GT_HQ}"
echo "  gt status              — check town status"
echo "  gt crew add <name> --rig ${RIG_NAME}  — create a workspace"
echo "  gt daemon start        — start Full Stack Mode"
