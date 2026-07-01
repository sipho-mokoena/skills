#!/usr/bin/env sh
set -eu

# gh-project-tracker installer — copies skill files to ~/.agents/skills/
# Usage: ./install.sh [--dir <path>]

TARGET="${HOME}/.agents/skills/gh-project-tracker"

while [ $# -gt 0 ]; do
    case "$1" in
        --dir) TARGET="$2"; shift 2 ;;
        --help) echo "Usage: $0 [--dir <target-dir>]"; exit 0 ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

echo "Checking prerequisites..."

if ! command -v gh >/dev/null 2>&1; then
    echo "ERROR: 'gh' CLI not found. Install from https://cli.github.com/"
    exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: 'uv' not found. Install from https://docs.astral.sh/uv/"
    exit 1
fi

mkdir -p "$TARGET"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cp "$SCRIPT_DIR/SKILL.md" "$TARGET/"
cp "$SCRIPT_DIR/project.py" "$TARGET/"

echo "Installed gh-project-tracker skill to:"
echo "  $TARGET"
echo ""
echo "Install via npx (Vercel skills ecosystem):"
echo "  npx skills add sipho-mokoena/skills --skill gh-project-tracker"
