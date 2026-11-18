# Reconstructing EchoLeak-style exfiltration attempts

Code and data for the paper. Replication of an EchoLeak-style attack with LangChain and
OpenClaw. The attempt is reconstructed afterwards from the mailbox (mail scan) and the
agent's session transcript (tool-call scan).

## Where the paper's numbers come from

| Paper | File(s) |
|-------|---------|
| Table 1, LangChain rows | `langchain/runs/{primed,unprimed}/summary.txt`, per run `receiver.log`, `agent_memory.log` |
| Table 1, OpenClaw rows | `openclaw/runs/full-{sub,inject}/summary.txt`, per run `receiver.log`, `agent.json` |
| Table 2, mail scan | `mailscan/results/final/scan_<n>_<condition>.json` (20 scans) |
| Tool-call scan, real runs | `toolcall-scan/full/findings.jsonl`, `toolcall-scan/full/summary.tsv` |
| Table 3, constructed cases | `toolcall-scan/full/synthetic-check.txt`, `toolcall-scan/synthetic/labels.jsonl` |

## Setup

- Mailpit: `docker compose up -d mailpit` (on 8025)
- Ollama with `qwen2.5:14b` on localhost:11434 (in the experiments with SSH tunnel to remote), context 32768 tokens
- Python3 with `pip install -r requirements.txt` (LangChain runs);
- OpenClaw 2026.9.9, agent `main` with tool profile `minimal` + `exec` tool

## Reproduce

- Corpora: `python3 corpora/build_mails.py` builds for openclaw, `python3 corpora/build_mails.py --langchain`,
  `./corpora/make_benign.sh`
- LangChain: `./langchain/run_langchain.sh 5` and `./langchain/run_langchain.sh 5 --no-priming`
- OpenClaw: start the gateway, then run commands in `openclaw/runs/full-batch.sh` from repo root
- Mail scan: `./mailscan/seeding.sh results/new`
- Tool-call scan: see below; constructed cases:
  `python3 toolcall-scan/synthetic/run_tests.py` (rebuilds the fixture DB)

## Tool-call scan
    python3 toolcall-scan/scan_toolcalls.py --db toolcall-scan/full/openclaw-agent.sqlite \
        --db toolcall-scan/synthetic/fixtures.sqlite \
        --allow-host localhost:8025 --allow-host 127.0.0.1:8025 --json > toolcall-scan/full/findings.jsonl
    python3 toolcall-scan/postfilter_findings.py --findings toolcall-scan/full/findings.jsonl \
        --run-dir openclaw/runs/full-sub --run-dir openclaw/runs/full-inject \
        --run-dir openclaw/runs/full-benign-mail --run-dir openclaw/runs/full-benign-normal \
        --out toolcall-scan/full/classified.jsonl --summary toolcall-scan/full/summary.tsv

## Notes

- The `run.json` files in `openclaw/runs/full-inject` still call the old corpus path
  `archive/corpora/mails.jsonl` -> changed to `corpora/mails-openclaw-injected.jsonl`
- The corpus mails carry the header `X-Corpus-Generator: generate_corpus.py`; this is a relic
- The password in the corpora is `Admin2026!`
