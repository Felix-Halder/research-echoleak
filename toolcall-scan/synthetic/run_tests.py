#!/usr/bin/env python3
"""Rebuild the synthetic fixture DB and compare scan_toolcalls.py with its labels."""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILDER = HERE / "build_fixtures.py"
SCANNER = HERE.parent / "scan_toolcalls.py"
DB = HERE / "fixtures.sqlite"
LABELS = HERE / "labels.jsonl"
LEVELS = {"LOW": 1, "MED": 2, "HIGH": 3}


def main():
    built = subprocess.run(
        [sys.executable, str(BUILDER)], capture_output=True, text=True
    )
    if built.returncode:
        print(built.stderr, file=sys.stderr)
        return built.returncode
    print(built.stdout.strip())

    labels = [
        json.loads(line)
        for line in LABELS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    allow_hosts = []
    for label in labels:
        for host in label.get("allow_hosts", []):
            if host not in allow_hosts:
                allow_hosts.append(host)

    cmd = [sys.executable, str(SCANNER), "--db", str(DB), "--json"]
    for host in allow_hosts:
        cmd.extend(["--allow-host", host])
    scanned = subprocess.run(cmd, capture_output=True, text=True)
    if scanned.returncode:
        print(scanned.stderr, file=sys.stderr)
        return scanned.returncode

    findings = {}
    for line in scanned.stdout.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        findings.setdefault((rec["session"], rec["seq"]), []).append(rec["level"])

    failures = 0
    for label in labels:
        key = (label["session"], label["seq"])
        got = max(findings.get(key, []), key=LEVELS.get, default="none")
        expected = label["expected"]
        ok = got == expected
        note = f"  [{label['note']}]" if label.get("note") else ""
        print(
            f"{'PASS' if ok else 'FAIL'}  {label['case']:<20} "
            f"expected={expected:<4} got={got:<4}{note}"
        )
        failures += not ok

    print(f"{len(labels) - failures}/{len(labels)} cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
