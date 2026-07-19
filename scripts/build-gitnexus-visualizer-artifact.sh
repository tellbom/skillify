#!/usr/bin/env bash
set -euo pipefail

SOURCE_ARCHIVE="${1:?usage: build-gitnexus-visualizer-artifact.sh SOURCE_ARCHIVE OUTPUT_TGZ}"
OUTPUT_TGZ="${2:?usage: build-gitnexus-visualizer-artifact.sh SOURCE_ARCHIVE OUTPUT_TGZ}"
EXPECTED_SOURCE_SHA="468138d074bb1c3bf4c0094a813d426a2146510d13a5f747c51b950a1f877c90"

if [[ "$(shasum -a 256 "$SOURCE_ARCHIVE" | awk '{print $1}')" != "$EXPECTED_SOURCE_SHA" ]]; then
  echo "GitNexus source archive checksum mismatch" >&2
  exit 1
fi

NODE_MAJOR="$(node --version | sed -E 's/^v([0-9]+).*/\1/')"
if [[ "$NODE_MAJOR" -lt 22 ]]; then
  echo "Node.js 22 or newer is required" >&2
  exit 1
fi

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
tar -xzf "$SOURCE_ARCHIVE" -C "$WORK_DIR"
SOURCE_ROOT="$(find "$WORK_DIR" -mindepth 1 -maxdepth 1 -type d | head -1)"

npm ci --prefix "$SOURCE_ROOT/gitnexus-shared"
npm ci --prefix "$SOURCE_ROOT/gitnexus-web"
npm ci --prefix "$SOURCE_ROOT/gitnexus"
npm run build --prefix "$SOURCE_ROOT/gitnexus"
npm prune --omit=dev --prefix "$SOURCE_ROOT/gitnexus"

RUNTIME_ROOT="$WORK_DIR/gitnexus-runtime-1.6.9"
mkdir -p "$RUNTIME_ROOT"
cp -R "$SOURCE_ROOT/gitnexus" "$RUNTIME_ROOT/gitnexus"
cp "$SOURCE_ROOT/LICENSE" "$RUNTIME_ROOT/LICENSE"
npm ls --all --json --prefix "$SOURCE_ROOT/gitnexus" > "$RUNTIME_ROOT/sbom.npm.json" || true

mkdir -p "$(dirname "$OUTPUT_TGZ")"
tar -czf "$OUTPUT_TGZ" -C "$WORK_DIR" "$(basename "$RUNTIME_ROOT")"
shasum -a 256 "$OUTPUT_TGZ"
