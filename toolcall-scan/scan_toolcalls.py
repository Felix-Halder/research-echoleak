#!/usr/bin/env python3
"""Detect EchoLeak-style exfiltration in OpenClaw session databases.

Reports text the model has seen that is reused in later tool-call arguments,
including encoded copies and shell expansions. Allow-listed URLs are skipped.
Usage: scan_toolcalls.py [--db PATH ...] [--agent NAME] [--session ID] [--json]
"""
import argparse, base64, json, os, re, sqlite3, subprocess, sys, urllib.parse, zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

# http(s) URL, ends at a space, a quote, a backslash, ')' or '<'/'>'
URL_RE = re.compile(r"https?://[^\s'\"\\)<>]+")
# curl/wget options whose value goes out with the request (body, header, cookie,
# user agent, basic auth, bearer token). Works for '-H value' and '--header=value',
# group 2 is the value without its quotes
DATA_RE = re.compile(r"(?:^|\s)(?:-d|--data(?:-raw|-binary|-urlencode)?|-F|--form"
                     r"|-H|--header|-b|--cookie|-A|--user-agent|-u|--user"
                     r"|--http-user|--http-password|--password|--oauth2-bearer)"
                     r"(?:\s+|=)(['\"]?)(.+?)\1(?=\s|$)")
# tool names that sound like they send something out (web_fetch, send_mail, ...)
OUTBOUND_TOOL = re.compile(r"fetch|http|browser|web|send|mail|message|upload|webhook|post", re.I)
# network tools or HTTP libraries in a command, plus bash's /dev/tcp and /dev/udp
NETWORK_TOOL_RE = re.compile(r"\b(curl|wget|nc|ncat|socat|telnet|scp|sftp|ftp|requests|urllib"
                             r"|httpx|aiohttp|http\.client)\b|/dev/(tcp|udp)/", re.I)
# cuts a value into words at spaces, quotes and URL/shell punctuation; not at - _ .
TOKEN_SPLIT_RE = re.compile(r"[\s'\"`,;()\[\]{}<>=&?#/\\:|]+")
# key-like: letter/digit chunks joined with - or _, e.g. sk-live-AB12cd
KEY_FORMAT_RE = re.compile(r"[A-Za-z0-9]{2,}(?:[-_][A-Za-z0-9]{2,})+")
# base64 or base64url run, at least 8 characters, optional = padding
B64_RE = re.compile(r"[A-Za-z0-9+/_-]{8,}={0,2}")
# hex run of at least 4 bytes (8 hex digits)
HEX_RE = re.compile(r"(?:[0-9a-fA-F]{2}){4,}")
# shell variable, $NAME or ${NAME...}
VAR_RE = re.compile(r"\$(?:\{[A-Za-z_][A-Za-z0-9_]*[^}]*\}|[A-Za-z_][A-Za-z0-9_]*)")
# variable names that probably hold a secret ($API_KEY, $DB_PASS, ...)
SECRET_NAME_RE = re.compile(r"key|token|secret|pass|auth|cred|cookie", re.I)
STRENGTH = {"key-format": 3, "mixed": 2, "number": 1, "text": 1,
            "embedded-command": 2, "secret-variable": 3, "variable": 1}

def kind_of(s):
    has_letter = any(c.isalpha() for c in s)
    has_digit = any(c.isdigit() for c in s)
    # '-', '_' and '.' are common in plain words, file names and hostnames
    has_special = any(not (c.isalnum() or c.isspace() or c in "-_.") for c in s)
    if has_letter and has_digit and KEY_FORMAT_RE.fullmatch(s):
        return "key-format"
    if (has_letter and has_digit) or has_special:
        return "mixed"
    return "number" if has_digit else "text"

def readable(raw, minlen):
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    ok = len(text) >= minlen and all(c.isprintable() or c.isspace() for c in text)
    return text if ok else None

def b64_decode(run):
    run = run.rstrip("=")
    return base64.b64decode(run.replace("-", "+").replace("_", "/") + "=" * (-len(run) % 4))

RUN_DECODERS = (
    ("base64", B64_RE, b64_decode),
    ("hex", HEX_RE, bytes.fromhex),
)

def gunzip(raw):
    """Inflate gzip or zlib data. The output is capped so a small input can't explode."""
    try:
        return zlib.decompressobj(zlib.MAX_WBITS | 32).decompress(raw, 1 << 20)
    except zlib.error:
        return None

def decodings(s, minlen):
    """Yield (encoding, text) for each way s can be decoded into readable text:
    percent-encoding, or a base64 or hex run, optionally gzip/zlib-compressed."""
    seen = {s}
    if "%" in s:
        text = urllib.parse.unquote(s)
        if text not in seen:
            seen.add(text)
            yield "percent", text
    for how, regex, decode in RUN_DECODERS:
        for m in regex.finditer(s):
            # '/' is a base64 character but also separates URL path segments, so try both
            for run in {m.group(), *m.group().split("/")}:
                try:
                    raw = decode(run)
                except ValueError:
                    continue
                text = readable(raw, minlen)
                if text is None:
                    inflated = gunzip(raw)
                    text = readable(inflated, minlen) if inflated else None
                    how_used = f"{how}+gzip"
                else:
                    how_used = how
                if text is not None and text not in seen:
                    seen.add(text)
                    yield how_used, text

def embedded_commands(s, backticks=True):
    found, i = [], 0
    while i < len(s):
        if s.startswith(("$(", "<(", ">("), i) and not s.startswith("$((", i):
            depth, j = 1, i + 2
            while j < len(s) and depth:
                depth += (s[j] == "(") - (s[j] == ")")
                j += 1
            found.append(s[i:j])
            i = j
        elif backticks and s[i] == "`" and s.find("`", i + 1) != -1:
            j = s.find("`", i + 1) + 1
            found.append(s[i:j])
            i = j
        else:
            i += 1
    return found

def add_matches(found, text, via, corpus, minlen):
    if len(text) >= minlen and text in corpus:
        found.setdefault(text, (kind_of(text), via))
        return
    for t in TOKEN_SPLIT_RE.split(text):
        if len(t) >= minlen and kind_of(t) != "text" and t in corpus:
            found.setdefault(t, (kind_of(t), via))

def host_port(s):
    u = urllib.parse.urlparse(s if "//" in s else "//" + s)
    try:
        return (u.hostname or "").lower(), u.port
    except ValueError:
        return (u.hostname or "").lower(), None

def load_allowlist(a):
    entries = list(a.allow_host)
    for f in a.allow_file:
        entries += Path(f).expanduser().read_text().splitlines()
    allow = set()
    for e in entries:
        e = e.strip()
        if e and not e.startswith("#"):
            hp = host_port(e)
            if hp[0]:
                allow.add(hp)
    return allow

def is_allowed(url, allow):
    host, port = host_port(url)
    return any((host == h or host.endswith("." + h)) and p in (None, port) for h, p in allow)

def find_dbs(a):
    if a.db:
        return [Path(p).expanduser().resolve() for p in a.db]
    root = Path(os.environ.get("OPENCLAW_STATE_DIR", Path.home() / ".openclaw")) / "agents"
    return sorted(p for p in root.glob("*/agent/openclaw-agent.sqlite")
                  if not a.agent or p.parent.parent.name == a.agent)

def decompress(blob):
    try:
        out = subprocess.run(["zstd", "-dc", "-q"], input=blob, capture_output=True, check=True)
    except FileNotFoundError:
        sys.exit("zstd binary not found (install it, e.g. apt install zstd)")
    except subprocess.CalledProcessError:
        return None
    return out.stdout.decode("utf-8", "replace")

def events(con):
    q = ("SELECT session_id, seq, created_at, event_json, event_zstd FROM transcript_events "
         "ORDER BY created_at, session_id, seq")
    for sid, seq, ts, ej, ez in con.execute(q):
        if ej is None and ez is not None:
            ej = decompress(ez)
        try:
            yield sid, seq, ts, json.loads(ej)
        except (TypeError, ValueError):
            continue

def leaves(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values(): yield from leaves(v)
    elif isinstance(obj, list):
        for v in obj: yield from leaves(v)

BOOKKEEPING_KEYS = {"id", "parentId", "timestamp", "type", "customType"}

def seen_text(ev):
    kind = ev.get("type")
    if kind == "message":
        msg = ev.get("message", {})
        return [] if msg.get("role") == "assistant" else list(leaves(msg.get("content")))
    if kind in ("custom", "custom_message", "compaction"):
        return [s for k, v in ev.items() if k not in BOOKKEEPING_KEYS for s in leaves(v)]
    return []

def toolcalls(msg):
    c = msg.get("content")
    for b in (c if isinstance(c, list) else []):
        if isinstance(b, dict) and b.get("type") == "toolCall":
            yield b

def call_args(b):
    for k in ("arguments", "args", "input", "params"):
        if k in b:
            v = b[k]
            if isinstance(v, str):
                try: v = json.loads(v)
                except ValueError: v = {"command": v}
            return v
    return {}

class Finding(NamedTuple):
    hosts: list
    tainted: list
    commands: list
    variables: list
    text: str

def analyze(name, args, corpus, allow, a):
    strs = list(leaves(args))
    urls = [u.rstrip(".,;:!?") for s in strs for u in URL_RE.findall(s)]
    bad_hosts = sorted({urllib.parse.urlparse(u).netloc for u in urls if not is_allowed(u, allow)})
    text = "\n".join(strs)
    if urls and not bad_hosts:
        return Finding([], [], [], [], text)

    outbound = bool(OUTBOUND_TOOL.search(name))
    can_send = bool(bad_hosts) or outbound or bool(NETWORK_TOOL_RE.search(text))
    commands = [c for s in strs for c in embedded_commands(s, backticks=not outbound)] \
        if can_send else []
    variables = list(dict.fromkeys(v for s in strs for v in VAR_RE.findall(s))) \
        if can_send and not outbound else []

    cand = set()
    for u in urls:
        parts = urllib.parse.urlparse(u)
        cand.add(urllib.parse.unquote(parts.path))
        cand.update(v for _, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    for s in strs:
        cand.update(m.group(2) for m in DATA_RE.finditer(s))
    if outbound:
        cand.update(strs)

    found = {}
    for c in cand:
        add_matches(found, c, "", corpus, a.min_taint_len)
        for how, plain in decodings(c, a.min_taint_len):
            add_matches(found, plain, how, corpus, a.min_taint_len)
    tainted = sorted(((v, kind, via) for v, (kind, via) in found.items()),
                     key=lambda t: (-STRENGTH[t[1]], t[0]))
    return Finding(bad_hosts, tainted, commands, variables, text)

def severity(f):
    strengths = [STRENGTH[kind] for _, kind, _ in f.tainted]
    if f.commands:
        strengths.append(STRENGTH["embedded-command"])
    if f.variables:
        secret = any(SECRET_NAME_RE.search(v) for v in f.variables)
        strengths.append(STRENGTH["secret-variable" if secret else "variable"])
    score = (2 if f.hosts else 0) + max(strengths, default=0)
    return "HIGH" if score >= 4 else "MED" if score == 3 else "LOW"

def scan(dbCon, agent, allow, a):
    corpus = ""
    for sessionId, seq, timestamp, ev in events(dbCon):
        corpus += "".join("\n" + s for s in seen_text(ev))
        if a.session and sessionId != a.session:
            continue
        msg = ev.get("message", {})
        if ev.get("type") != "message" or msg.get("role") != "assistant":
            continue
        for b in toolcalls(msg):
            name = str(b.get("name") or b.get("toolName") or "?")
            f = analyze(name, call_args(b), corpus, allow, a)
            if not (f.hosts or f.tainted or f.commands or f.variables):
                continue
            level = severity(f)
            rec = {"time": datetime.fromtimestamp(timestamp / 1000, timezone.utc).strftime("%F %T"),
                   "agent": agent, "session": sessionId, "seq": seq, "tool": name, "level": level,
                   "unlisted_hosts": f.hosts,
                   "tainted": [{"value": v, "kind": k, "encoding": via} for v, k, via in f.tainted],
                   "embedded_commands": f.commands, "variables": f.variables, "args": f.text}
            if a.json:
                print(json.dumps(rec))
            else:
                shown = [f"{v} ({k}{', via ' + via if via else ''})" for v, k, via in f.tainted]
                print(f"{rec['time']} {level:4} {agent}/{sessionId[:8]} #{seq} {name}"
                      f"\n    hosts={f.hosts} tainted={shown} commands={f.commands}"
                      f" variables={f.variables}\n    {f.text}")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--db", action="append", help="scan these databases instead of auto-discovering")
    p.add_argument("--agent", help="only this agent (auto-discovery only)")
    p.add_argument("--session", help="only this session id")
    p.add_argument("--allow-host", action="append", default=[], metavar="HOST|URL",
                   help="allowed host (optionally :PORT) or URL; repeatable")
    p.add_argument("--allow-file", action="append", default=[], metavar="FILE",
                   help="file with one allowed URL/host per line; '#' starts a comment")
    p.add_argument("--min-taint-len", type=int, default=6,
                   help="shortest reused value or token that counts as a match")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    allow = load_allowlist(a)

    dbs = find_dbs(a)
    if not dbs:
        sys.exit("no databases found (use --db PATH or set OPENCLAW_STATE_DIR)")

    for db in dbs:
        agent = db.parent.parent.name
        try:
            con = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
            scan(con, agent, allow, a)
        except sqlite3.Error as e:
            print(f"skipping {db}: {e}", file=sys.stderr)
