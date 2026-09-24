#!/usr/bin/env sh
# Orca Code installer — downloads the right prebuilt binary from GitHub Releases.
# Usage: curl -fsSL https://raw.githubusercontent.com/Nethyric/orca-code/main/install.sh | sh
set -eu

REPO="Nethyric/orca-code"
INSTALL_DIR="${ORCA_INSTALL_DIR:-$HOME/.local/bin}"

say() { printf '\033[36m🐋 %s\033[0m\n' "$*"; }
err() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

os=$(uname -s | tr '[:upper:]' '[:lower:]')
arch=$(uname -m)
case "$arch" in
  x86_64|amd64) arch=amd64 ;;
  aarch64|arm64) arch=arm64 ;;
  *) err "unsupported architecture: $arch" ;;
esac
case "$os" in
  linux|darwin) ;;
  *) err "unsupported OS: $os (Windows: download orca-windows-amd64.exe from Releases)" ;;
esac

asset="orca-${os}-${arch}"
url="https://github.com/${REPO}/releases/latest/download/${asset}"

say "downloading ${asset} …"
mkdir -p "$INSTALL_DIR"
tmp=$(mktemp)
if command -v curl >/dev/null 2>&1; then
  curl -fsSL -o "$tmp" "$url" || err "download failed — check https://github.com/${REPO}/releases"
else
  wget -qO "$tmp" "$url" || err "download failed — check https://github.com/${REPO}/releases"
fi
install -m 0755 "$tmp" "$INSTALL_DIR/orca"
rm -f "$tmp"

say "installed to $INSTALL_DIR/orca"
case ":$PATH:" in
  *":$INSTALL_DIR:"*) ;;
  *) say "note: add it to your PATH →  export PATH=\"$INSTALL_DIR:\$PATH\"" ;;
esac
"$INSTALL_DIR/orca" version
say "done. Run 'orca' inside a project to start."
