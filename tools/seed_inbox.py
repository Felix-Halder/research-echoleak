#!/usr/bin/env python3
"""Send the mails of a JSONL corpus to Mailpit over SMTP (localhost:1025).

Usage: python3 seed_inbox.py CORPUS.jsonl
"""

import json
import smtplib
import sys
from email.mime.text import MIMEText

SMTP_HOST = "localhost"
SMTP_PORT = 1025

if len(sys.argv) != 2:
    print(f"usage: {sys.argv[0]} CORPUS.jsonl", file=sys.stderr)
    sys.exit(2)
path = sys.argv[1]

with open(path, encoding="utf-8") as fh, smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
    for line in fh:
        if not line.strip():
            continue
        m = json.loads(line)
        html = m.get("body_html") or ""
        body = html or m.get("body_text", "")
        msg = MIMEText(body, "html" if html else "plain", "utf-8")
        msg["Subject"] = m.get("subject", "")
        msg["From"] = m.get("from_addr", "")
        msg["To"] = m.get("to_addr", "")
        if m.get("date"):
            msg["Date"] = m["date"]
        server.send_message(msg)
        print(f"[seed] sent: {msg['Subject']!r} -> {msg['To']}")

print(f"[seed] done. {path} injected into Mailpit.")
