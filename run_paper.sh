#!/usr/bin/env bash
# Adopted PAPER system; fresh virtual session, no exchange orders.
set -euo pipefail
cd "$(dirname "$0")"
DURATION_SECONDS="${1:-10800}"
if [ "$#" -gt 1 ]; then echo "Usage: bash run_paper.sh [1200|3600|10800|21600]" >&2; exit 2; fi
case "$DURATION_SECONDS" in
  1200|3600|10800|21600) ;;
  *) echo "Unsupported duration: $DURATION_SECONDS" >&2; exit 2 ;;
esac
if command -v termux-wake-lock >/dev/null; then termux-wake-lock; fi
mkdir -p runs
RUN_DIR="runs/vortex-approved-$(date -u +%Y%m%d-%H%M%S)-$$"
printf '%s\n' "$RUN_DIR" > runs/latest-paper-path.txt
exec python -m vortex.session --duration-seconds "$DURATION_SECONDS" --starting-equity 20 \
  --diagnostics --output "$RUN_DIR"
