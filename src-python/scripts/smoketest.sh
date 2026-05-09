#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# src-python/scripts/smoketest.sh — End-to-end smoke test for the W1 backend
# ──────────────────────────────────────────────────────────────────────
#
# Walks the API through a full upload → slurmify → SSE-progress →
# download cycle, then opens the resulting audio file in the macOS
# default player.  Reports clearly which step failed if any.
#
# Usage:
#   ./src-python/scripts/smoketest.sh PORT INPUT_AUDIO_PATH
#
# Example:
#   ./src-python/scripts/smoketest.sh 50847 ~/Music/test-track.wav
#
# Requires: curl, jq, open (macOS).  jq is usually preinstalled or:
#   brew install jq
# ──────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Argument parsing + sanity checks ───────────────────────────────────
if [ $# -ne 2 ]; then
    echo "usage: $0 PORT INPUT_AUDIO_PATH" >&2
    echo "  example: $0 50847 ~/Music/test-track.wav" >&2
    exit 2
fi

PORT="$1"
INPUT="$2"
BASE="http://127.0.0.1:${PORT}"

# Resolve ~ in INPUT (zsh + bash both expand it before running, but be safe).
INPUT="${INPUT/#\~/$HOME}"

if ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
    echo "ERROR: PORT '$PORT' is not a number" >&2
    exit 2
fi
if [ ! -f "$INPUT" ]; then
    echo "ERROR: input file does not exist: $INPUT" >&2
    exit 2
fi
if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq not installed (brew install jq)" >&2
    exit 2
fi

echo "=== Slurmify W1 backend smoke test ==="
echo "  PORT  : $PORT"
echo "  INPUT : $INPUT"
echo

# ── Step 1: health ─────────────────────────────────────────────────────
echo "[1/5] GET /health …"
HEALTH=$(curl -fsS "${BASE}/health") || {
    echo "FAILED — is the server running on port $PORT?"
    exit 1
}
echo "    response: $HEALTH"

# ── Step 2: upload ─────────────────────────────────────────────────────
echo
echo "[2/5] POST /upload  ($(basename "$INPUT")) …"
UPLOAD=$(curl -fsS -F "file=@${INPUT}" "${BASE}/upload")
FILE_ID=$(echo "$UPLOAD" | jq -r .file_id)
DURATION=$(echo "$UPLOAD" | jq -r .duration_sec)
CHANNELS=$(echo "$UPLOAD" | jq -r .channels)
SR=$(echo "$UPLOAD" | jq -r .sample_rate)
EXTRACTED=$(echo "$UPLOAD" | jq -r .was_extracted)
echo "    file_id      : $FILE_ID"
echo "    duration_sec : $DURATION"
echo "    channels     : $CHANNELS  (1=mono, 2=stereo)"
echo "    sample_rate  : $SR"
echo "    was_extracted: $EXTRACTED  (true if ffmpeg ran on a video file)"

# ── Step 3: slurmify ───────────────────────────────────────────────────
echo
echo "[3/5] POST /slurmify  (speed=2.0, resolution=1/16) …"
SLURM_RES=$(curl -fsS -X POST "${BASE}/slurmify" \
    -H 'Content-Type: application/json' \
    -d "{\"file_id\": \"${FILE_ID}\", \"speed\": 2.0, \"resolution\": \"1/16\"}")
JOB_ID=$(echo "$SLURM_RES" | jq -r .job_id)
echo "    job_id: $JOB_ID"

# ── Step 4: progress (SSE → final payload) ─────────────────────────────
echo
echo "[4/5] GET /jobs/${JOB_ID}/progress  (SSE) …"
echo "    streaming progress (one line per update):"

# Use curl -N (no buffering) and feed the stream to a small awk that
# parses each "data: {...}" line, prints a progress bar, and stops at
# done:true.  Capture the final payload so we can extract output_id.
FINAL=$(curl -fsSN "${BASE}/jobs/${JOB_ID}/progress" | awk '
    /^data:/ {
        sub(/^data: */, "", $0)
        # Print every payload to stderr so the user sees progress live.
        printf "      %s\n", $0 > "/dev/stderr"
        # Save the latest payload — when done arrives, it'\''s our output.
        last = $0
        if (index($0, "\"done\":true") > 0) {
            print last
            exit
        }
    }
')

if [ -z "$FINAL" ]; then
    echo "FAILED — SSE stream closed without a done payload"
    exit 1
fi

ERROR=$(echo "$FINAL" | jq -r .error)
OUTPUT_ID=$(echo "$FINAL" | jq -r .output_id)

if [ "$ERROR" != "null" ] && [ -n "$ERROR" ]; then
    echo "    error: $ERROR"
    echo "FAILED at slurmify step"
    exit 1
fi

echo "    output_id: $OUTPUT_ID"

# ── Step 5: download + open ────────────────────────────────────────────
OUT_PATH="/tmp/slurm-smoketest-$(date +%s).wav"
echo
echo "[5/5] GET /files/${OUTPUT_ID}  →  $OUT_PATH"
curl -fsS "${BASE}/files/${OUTPUT_ID}" -o "$OUT_PATH"
SIZE=$(stat -f %z "$OUT_PATH" 2>/dev/null || stat -c %s "$OUT_PATH")
echo "    saved $SIZE bytes"

if [ "$SIZE" -lt 1000 ]; then
    echo "WARNING — output file is suspiciously small (<1 KB)"
fi

echo
echo "=== ✓ ALL FIVE STEPS PASSED ==="
echo "Opening $OUT_PATH in default audio player…"
open "$OUT_PATH" 2>/dev/null || echo "(open failed — file is at $OUT_PATH)"
