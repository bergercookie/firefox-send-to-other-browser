#!/usr/bin/env bash
# Bootstrap script: installs `just` (https://just.systems), which every other
# task in this repo runs through. Usage:
#
#   scripts/install-just.sh [install-dir]     # default: ~/.local/bin
#
# JUST_VERSION overrides the pinned release below. Needs curl (or wget) and tar.
set -euo pipefail

dest="${1:-$HOME/.local/bin}"
version="${JUST_VERSION:-1.40.0}"

if command -v just >/dev/null 2>&1; then
    echo "just is already installed: $(command -v just) ($(just --version))"
    exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

if command -v curl >/dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -fsSL https://just.systems/install.sh -o "$tmp/install.sh"
elif command -v wget >/dev/null 2>&1; then
    wget -q https://just.systems/install.sh -O "$tmp/install.sh"
else
    echo "need curl or wget to download just" >&2
    exit 1
fi

mkdir -p "$dest"
bash "$tmp/install.sh" --to "$dest" --tag "$version"

echo "installed $("$dest/just" --version) to $dest"
case ":$PATH:" in
    *":$dest:"*) ;;
    *) echo "note: $dest is not on your PATH; add it to your shell profile" ;;
esac
