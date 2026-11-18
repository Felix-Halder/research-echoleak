#!/bin/sh
#   digest.sh [N] [MODE] [MAXCHARS] [OFFSET]   defaults: 50 html 4000 0
#   MODE: text | html | both. OFFSET batches fetches, because OpenClaw cuts a
#   single tool result at 16000 characters.
N="${1:-50}"; MODE="${2:-html}"; MAX="${3:-4000}"; OFFSET="${4:-0}"

case "$N"   in ''|*[!0-9]*) echo "N must be a number" >&2; exit 1;; esac
case "$MAX" in ''|*[!0-9]*) echo "MAXCHARS must be a number" >&2; exit 1;; esac
case "$OFFSET" in ''|*[!0-9]*) echo "OFFSET must be a number" >&2; exit 1;; esac
case "$MODE" in text|html|both) ;; *) echo "MODE must be text, html or both" >&2; exit 1;; esac

BASE="http://localhost:8025/api/v1"
curl -s "$BASE/messages?start=$OFFSET&limit=$N" | jq -r '.messages[].ID' | while read -r id; do
  curl -s "$BASE/message/$id" | jq -c --arg mode "$MODE" --argjson max "$MAX" '
    def clean: (. // "") | gsub("[[:cntrl:]]"; " ") | .[0:$max];
    { from: .From.Address, subject: .Subject, date: .Date }
    + (if $mode == "text" or $mode == "both" then {text: (.Text | clean)} else {} end)
    + (if $mode == "html" or $mode == "both" then {html: (.HTML | clean)} else {} end)'
done
