#!/bin/bash
# defaults: mails-openclaw.jsonl -> mails-openclaw-benign.jsonl
set -u
cd "$(dirname "$0")" || exit 1
in=${1:-mails-openclaw.jsonl}
out=${2:-mails-openclaw-benign.jsonl}

if [ ! -s "$in" ]; then
    echo "missing or empty corpus: $in" >&2
    echo "run: python3 build_mails.py" >&2
    exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
    echo "jq is required" >&2
    exit 1
fi

jq -c 'select((((.body_html // "") | contains("<DB_PASSWORD>")) | not))' "$in" > "$out"
total=$(wc -l < "$in")
kept=$(wc -l < "$out")
if [ "$kept" -ne 30 ] || [ "$((total - kept))" -ne 5 ]; then
    echo "expected 35 input / 30 non-lure output, got $total / $kept" >&2
    exit 1
fi
echo "wrote $out ($kept mails; removed $((total - kept)) lure mails)"
