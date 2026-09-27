"""Extract Sissi's own prompts from Claude Code + Codex sessions (local only)."""
import json, glob, os, re

HOME = os.path.expanduser("~")
OUT = os.path.join(HOME, "voice-twin/data/sessions.jsonl")

SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+|[A-Za-z0-9_]*(?:KEY|TOKEN|SECRET)[A-Za-z0-9_]*\s*=\s*\S+)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")

def scrub(t):
    t = SECRET.sub("<SECRET>", t)
    t = EMAIL.sub("<EMAIL>", t)
    return PHONE.sub("<PHONE>", t)

def keep(t):
    t = t.strip()
    if not t or t.startswith(("<", "Caveat:", "# Files mentioned", "# AGENTS.md", "[http", "http")) or t.count("\n") > 60 or "[Request interrupted" in t:
        return False
    return 3 <= len(t) <= 4000

def texts(content):
    if isinstance(content, str):
        return [content]
    return [c.get("text", "") for c in content or [] if c.get("type") in ("text", "input_text")]

seen, rows = set(), []

def add(src, ts, cwd, text, prev):
    for t in texts(text):
        if keep(t) and t not in seen:
            seen.add(t)
            rows.append({"source": src, "ts": ts, "project": os.path.basename(cwd or ""),
                         "text": scrub(t.strip()), "prev": scrub((prev or "")[-800:])})

for f in glob.glob(f"{HOME}/.claude/projects/*/*.jsonl"):
    prev = ""
    for line in open(f, errors="ignore"):
        try: d = json.loads(line)
        except Exception: continue
        m = d.get("message") or {}
        if d.get("type") == "assistant":
            prev = " ".join(texts([c for c in m.get("content", []) if isinstance(c, dict)])) or prev
        elif d.get("type") == "user" and not d.get("isMeta") and not d.get("isSidechain"):
            add("claude", d.get("timestamp"), d.get("cwd"), m.get("content"), prev)

for f in glob.glob(f"{HOME}/.codex/sessions/**/*.jsonl", recursive=True):
    prev, cwd = "", ""
    for line in open(f, errors="ignore"):
        try: d = json.loads(line)
        except Exception: continue
        p = d.get("payload") or {}
        if d.get("type") == "session_meta": cwd = p.get("cwd")
        if d.get("type") == "response_item" and p.get("type") == "message":
            if p.get("role") == "assistant":
                prev = " ".join(c.get("text", "") for c in p.get("content", [])) or prev
            elif p.get("role") == "user":
                add("codex", d.get("timestamp"), cwd, [c for c in p.get("content", []) if c.get("type") == "input_text"], prev)

rows.sort(key=lambda r: r["ts"] or "")
with open(OUT, "w") as o:
    for r in rows: o.write(json.dumps(r, ensure_ascii=False) + "\n")
from collections import Counter
print(len(rows), Counter(r["source"] for r in rows))
