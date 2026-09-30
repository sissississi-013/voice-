"""Extract your own prompts from Claude Code + Codex session logs (runs locally; nothing is uploaded).

    python3 extract_sessions.py        # -> data/sessions.jsonl

Keeps only messages you typed (no assistant text, tool output, system/env blocks or pasted
attachments), scrubs secrets / emails / phone numbers, and dedupes.
"""
import glob
import json
import os
import re
from collections import Counter
from pathlib import Path

HOME = os.path.expanduser("~")
OUT = Path(__file__).parent / "data/sessions.jsonl"
CLAUDE_GLOB = f"{HOME}/.claude/projects/*/*.jsonl"
CODEX_GLOB = f"{HOME}/.codex/sessions/**/*.jsonl"

SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+|[A-Za-z0-9_]*(?:KEY|TOKEN|SECRET)[A-Za-z0-9_]*\s*=\s*\S+)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
NOISE_PREFIXES = ("<", "Caveat:", "# Files mentioned", "# AGENTS.md", "[http", "http")


def scrub(t):
    t = SECRET.sub("<SECRET>", t)
    t = EMAIL.sub("<EMAIL>", t)
    return PHONE.sub("<PHONE>", t)


def keep(t):
    t = t.strip()
    if not t or t.startswith(NOISE_PREFIXES) or t.count("\n") > 60 or "[Request interrupted" in t:
        return False
    return 3 <= len(t) <= 4000


def texts(content):
    if isinstance(content, str):
        return [content]
    return [c.get("text", "") for c in content or [] if c.get("type") in ("text", "input_text")]


def read_jsonl(path):
    for line in open(path, errors="ignore"):
        try:
            yield json.loads(line)
        except Exception:
            continue


def claude_messages(path):
    """Yield (timestamp, cwd, content, previous assistant text) for each user turn."""
    prev = ""
    for d in read_jsonl(path):
        m = d.get("message") or {}
        if d.get("type") == "assistant":
            prev = " ".join(texts([c for c in m.get("content", []) if isinstance(c, dict)])) or prev
        elif d.get("type") == "user" and not d.get("isMeta") and not d.get("isSidechain"):
            yield d.get("timestamp"), d.get("cwd"), m.get("content"), prev


def codex_messages(path):
    prev, cwd = "", ""
    for d in read_jsonl(path):
        p = d.get("payload") or {}
        if d.get("type") == "session_meta":
            cwd = p.get("cwd")
        if d.get("type") == "response_item" and p.get("type") == "message":
            if p.get("role") == "assistant":
                prev = " ".join(c.get("text", "") for c in p.get("content", [])) or prev
            elif p.get("role") == "user":
                yield d.get("timestamp"), cwd, [c for c in p.get("content", []) if c.get("type") == "input_text"], prev


def extract(claude_files, codex_files):
    seen, rows = set(), []
    sources = [("claude", f, claude_messages) for f in claude_files] + [("codex", f, codex_messages) for f in codex_files]
    for src, path, reader in sources:
        for ts, cwd, content, prev in reader(path):
            for t in texts(content):
                if keep(t) and t not in seen:
                    seen.add(t)
                    rows.append({"source": src, "ts": ts, "project": os.path.basename(cwd or ""),
                                 "text": scrub(t.strip()), "prev": scrub((prev or "")[-800:])})
    return sorted(rows, key=lambda r: r["ts"] or "")


def main():
    rows = extract(glob.glob(CLAUDE_GLOB), glob.glob(CODEX_GLOB, recursive=True))
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w") as o:
        for r in rows:
            o.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(len(rows), dict(Counter(r["source"] for r in rows)), "->", OUT)


if __name__ == "__main__":
    main()
