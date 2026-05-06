#!/bin/bash
# Run this on your Mac to grab the Slurmify app screenshots for the deck
# Usage: bash grab_screens.sh
cd "$(dirname "$0")"
# Capture window containing "Slurmer" in Chrome
screencapture -l $(osascript -e 'tell app "Google Chrome" to id of front window') \
  -x slurm_screen_full.png 2>/dev/null || screencapture -x slurm_screen_full.png
echo "Saved slurm_screen_full.png"
