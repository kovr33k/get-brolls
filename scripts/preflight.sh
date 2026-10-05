#!/usr/bin/env bash
# Compatibility entry point; the maintained release uses Windows/PowerShell.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python "$REPO_ROOT/scripts/preflight.py" "$@"
