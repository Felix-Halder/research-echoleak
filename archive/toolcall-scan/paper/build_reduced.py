import json, os, sqlite3, sys
HOME = os.path.expanduser("~")
REPO = f"{HOME}/forschungsmodul"
SNAP = "/tmp/openclaw-agent-full.sqlite"          # read-only .backup of the main DB, made beforehand
OUT_DIR = f"{REPO}/toolcall-scan/paper"
OUT = f"{OUT_DIR}/openclaw-agent.sqlite"
RUN_DIRS = ["openclaw/runs/test-sub", "openclaw/runs/test-inject",
            "openclaw/runs/final-benign-mail", "openclaw/runs/final-benign-normal"]

if os.path.exists(OUT_DIR):
    sys.exit(f"ABORT: {OUT_DIR} exists")

ids = {}
for rd in RUN_DIRS:
    base = f"{REPO}/{rd}"
    for r in sorted(os.listdir(base)):
        if not r.startswith("run_"):
            continue
        run = json.load(open(f"{base}/{r}/run.json"))
        sid = (run.get("session_id") or "").strip()
        if not sid:
            aj = json.load(open(f"{base}/{r}/agent.json"))
            sid = aj["result"]["meta"]["agentMeta"]["sessionId"]
        ids[sid] = f"{rd.split('/')[-1]}/{r}"

tier1 = set()
with open(f"{REPO}/toolcall-scan/tier1-summary.tsv") as f:
    for line in f:
        parts = line.split("\t")
        if len(parts) > 3 and parts[0] != "condition" and len(parts[2]) == 36:
            tier1.add(parts[2])
print("sessions from run dirs:", len(ids), "| tier1-summary:", len(tier1), "| equal:", set(ids) == tier1)
if len(ids) != 19 or set(ids) != tier1:
    sys.exit("ABORT: session id mismatch")

src = sqlite3.connect(f"file:{SNAP}?mode=ro", uri=True)
ddl = [r[0] for r in src.execute(
    "select sql from sqlite_master where tbl_name='transcript_events' and sql is not null "
    "order by type='table' desc")]
total = src.execute("select count(distinct session_id), count(*) from transcript_events").fetchone()
counts = dict(src.execute(
    f"select session_id, count(*) from transcript_events where session_id in ({','.join('?'*len(ids))}) group by 1",
    list(ids)).fetchall())
missing = [s for s in ids if s not in counts]
print("full snapshot sessions/events:", total)
if missing:
    sys.exit(f"ABORT: missing in DB: {missing}")

os.makedirs(OUT_DIR)
dst = sqlite3.connect(OUT)
for stmt in ddl:
    dst.execute(stmt)
cols = [r[1] for r in src.execute("pragma table_info(transcript_events)")]
rows = src.execute(
    f"select {','.join(cols)} from transcript_events where session_id in ({','.join('?'*len(ids))})",
    list(ids)).fetchall()
dst.executemany(f"insert into transcript_events ({','.join(cols)}) values ({','.join('?'*len(cols))})", rows)
dst.commit()
check = dst.execute("select count(distinct session_id), count(*) from transcript_events").fetchone()
tables = [r[0] for r in dst.execute("select name from sqlite_master where type='table'")]
dst.execute("vacuum")
dst.close()
print("reduced sessions/events:", check, "| tables:", tables)
for sid, name in sorted(ids.items(), key=lambda kv: kv[1]):
    print(f"{name}\t{sid}\t{counts[sid]}")
