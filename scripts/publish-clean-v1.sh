#!/usr/bin/env bash
# Publish Orca Code as a clean v1.0.0 repository.
# Usage: GITHUB_TOKEN=... ./scripts/publish-clean-v1.sh
set -euo pipefail

: "${GITHUB_TOKEN:?Set GITHUB_TOKEN locally; never paste it into chat}"
REPO="Nethyric/orca-code"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cd "$ROOT"
export PATH="${PATH}:/usr/local/go/bin"
gofmt -w .
go vet ./...
go test -race -count=1 ./...
CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o "$TMP/orca" ./cmd/orca

# Build a genuinely new root commit: no old Python files and no old history.
cd "$TMP"
git init -q -b main
git config user.name "Nethyric"
git config user.email "Nethyric@users.noreply.github.com"
cp -a "$ROOT/." "$TMP/"
rm -rf .git dist orca orca.exe
# Keep generated build outputs out of the source commit.
printf '/orca\n/orca.exe\ndist/\n*.test\n.orca/settings.local.json\n' > .gitignore
git add -A
git commit -qm 'Orca Code 1.0.0 — secure terminal coding agent'
REMOTE="https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO}.git"
git remote add origin "$REMOTE"
git push -q --force origin main

# Remove every remote tag, then publish exactly one tag.
for ref in $(git ls-remote --tags --refs "$REMOTE" | awk '{print $2}'); do
  tag=${ref#refs/tags/}
  git push -q "$REMOTE" --delete "$tag" 2>/dev/null || true
done
git tag v1.0.0
git push -q "$REMOTE" v1.0.0

# Remove every existing GitHub Release except the new one.
if command -v gh >/dev/null 2>&1; then
  gh release list --repo "$REPO" --limit 100 --json tagName --jq '.[].tagName' |
    while read -r tag; do
      [ "$tag" = "v1.0.0" ] || gh release delete "$tag" --repo "$REPO" --yes || true
    done
fi

echo "Published clean v1.0.0 with a fresh root commit and no legacy releases."
