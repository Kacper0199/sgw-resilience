#!/bin/sh
# Thin wrapper for macOS and Linux. The build itself is docs/build.py (cross-OS).
# Usage: docs/build.sh [all|prd|briefing|diagrams|figures|lint] [--final] [--no-lock]
set -e
cd "$(dirname "$0")/.."
exec uv run python docs/build.py "${@:-all}"
