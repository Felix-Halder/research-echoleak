#!/bin/bash
# Mail-scan ablation: inject N payloads into the large corpus and scan it.
cd "$(dirname "$0")" || exit 1
out=${1:-results/new}
mkdir -p "$out"

run() {
    local suffix=$1; shift
    for n in 3 5 7 10 15; do
        f="$out/corpus-injected-$n-$suffix-large.jsonl"
        cp ../corpora/corpus-large.jsonl "$f"
        python3 apply_injections.py "$@" -n "$n" -i "$f"
        python3 detect_echo_leak.py -i "$f" -o "$out/scan_${n}_$suffix.json" \
            > "$out/scan_${n}_$suffix.log" 2>&1
    done
}

run
run altered --altered
run negatives --hard-negatives
run altered-negatives --altered --hard-negatives
