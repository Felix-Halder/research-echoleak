for d in full-sub full-inject full-benign-mail full-benign-normal; do
    [ ! -e "openclaw/runs/$d" ] || { echo "ABORT: openclaw/runs/$d exists"; exit 1; }
done
export BATCH=full OPENCLAW_BIN="openclaw --profile clean"
P=openclaw/openclaw-prompt-lc-primed-portfix-batched.txt
echo "start $(date -Is)"
./openclaw/run_openclaw.sh 2 --corpus corpora/mails-openclaw-benign.jsonl --prompt openclaw/openclaw-benign-prompt-batched.txt --out openclaw/runs/full-benign-mail --label benign-mail --expected-lines 30; echo "benign-mail exit $?"
./openclaw/run_openclaw.sh 1 --corpus corpora/mails-openclaw-benign.jsonl --prompt openclaw/openclaw-normal-prompt.txt --out openclaw/runs/full-benign-normal --label benign-normal --expected-lines 30; echo "benign-normal exit $?"
./openclaw/run_openclaw.sh 8 --corpus corpora/mails-openclaw.jsonl --prompt "$P" --out openclaw/runs/full-sub --label sub; echo "sub exit $?"
./openclaw/run_openclaw.sh 8 --corpus corpora/mails-openclaw-injected.jsonl --prompt "$P" --out openclaw/runs/full-inject --label inject; echo "inject exit $?"
echo "done $(date -Is)"
