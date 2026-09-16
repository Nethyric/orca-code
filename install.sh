#!/usr/bin/env bash
# Orca Code installer — zero-dependency AI coding agent (Python 3.9+)
# Usage: curl -fsSL https://raw.githubusercontent.com/Nethyric/orca-code/main/install.sh | bash
set -euo pipefail

REPO="https://github.com/Nethyric/orca-code"
ZIP="$REPO/archive/refs/heads/main.zip"   # install source: no git needed
say() { printf '\033[38;5;81m🐋 %s\033[0m\n' "$*"; }
err() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; }

# ── 1. find a suitable Python ────────────────────────────────────────────
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      PY="$cand"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  err "Python 3.9+ not found. Install it from https://www.python.org/downloads/ and retry."
  exit 1
fi
say "using $PY ($($PY --version 2>&1))"

# ── 2. pick an install strategy for this platform ────────────────────────
if command -v pipx >/dev/null 2>&1; then
  say "installing with pipx (isolated)"
  pipx install "$ZIP"
elif ! $PY -m pip install "$ZIP" 2>/dev/null; then
  # externally-managed environment (PEP 668): Ubuntu 23.04+/Debian 12+/Fedora 38+
  say "system Python is externally managed — installing to --user"
  $PY -m pip install --user "$ZIP" 2>/dev/null || \
    $PY -m pip install --break-system-packages "$ZIP"
fi

# ── 3. make sure it's on PATH ────────────────────────────────────────────
BIN="$HOME/.local/bin"
if ! command -v orca >/dev/null 2>&1; then
  if [ -x "$BIN/orca" ]; then
    case ":$PATH:" in
      *":$BIN:"*) ;;
      *)
        err "orca is installed at $BIN/orca but that directory is not on your PATH."
        echo "    Fix (bash/zsh):  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
        exit 1
        ;;
    esac
  else
    err "installation did not produce an 'orca' command — see messages above"
    exit 1
  fi
fi

# ── 4. verify ────────────────────────────────────────────────────────────
say "installed: $(orca --version)"
say "next:  orca auth login   → add a provider key (validated live)"
say "      orca               → start coding"
