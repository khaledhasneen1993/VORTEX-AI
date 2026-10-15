#!/usr/bin/env bash
# Explicit 913 PAPER session; default launcher remains strategy 911.
set -euo pipefail
cd "$(dirname "$0")"
if [ "$#" -gt 1 ]; then
  echo "Usage: bash run_913.sh [1200|3600|10800|14400|21600]" >&2
  exit 2
fi
DURATION_SECONDS="${1:-3600}"
case "$DURATION_SECONDS" in
  1200|3600|10800|14400|21600) ;;
  *) echo "Unsupported duration: $DURATION_SECONDS" >&2; exit 2 ;;
esac
if command -v termux-wake-lock >/dev/null; then termux-wake-lock; fi
mkdir -p runs
RUN_DIR="runs/vortex-913-$(date -u +%Y%m%d-%H%M%S)-$$"
printf '%s\n' "$RUN_DIR" > runs/latest-paper-path.txt
exec python -m vortex.session --strategy 913 --duration-seconds "$DURATION_SECONDS" \
  --starting-equity "${STARTING_EQUITY:-100}" --diagnostics --output "$RUN_DIR"
