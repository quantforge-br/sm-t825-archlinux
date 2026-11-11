#!/usr/bin/env bash
# Compatibility entry point: always use the bounded, recovery-aware runner.
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
if [ -n "${2:-}" ]; then export T825_REPORT_DIR=$2; fi
if [ -n "${T825_SSH_HOST:-}" ]; then export T825_SSH_TARGET=$T825_SSH_HOST; fi
if [ "$#" -gt 0 ]; then
    exec "$HERE/tools/t825-gnss-auto-cycle.sh" "$1"
fi
exec "$HERE/tools/t825-gnss-auto-cycle.sh"
