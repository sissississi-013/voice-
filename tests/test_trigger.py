"""The @v trigger regex is shared by extension/content.js and mac/VoiceHelper.swift; keep them in sync."""
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
TRIGGER = re.compile(r"(^|\s)@v(?:\s+(.*))?$", re.S)


def parse(text):
    m = TRIGGER.search(text)
    return None if not m else (text[:m.start()].strip(), (m.group(2) or "").strip())


def test_trigger_cases():
    assert parse("@v") == ("", "")
    assert parse("@v say no nicely") == ("", "say no nicely")
    assert parse("cant come tonight sorry @v") == ("cant come tonight sorry", "")
    assert parse("email me@vercel.com") is None       # no false positive inside words/emails
    assert parse("hello") is None


def test_pattern_is_identical_in_both_clients():
    js = (ROOT / "extension/content.js").read_text()
    swift = (ROOT / "mac/VoiceHelper.swift").read_text()
    assert r"/(^|\s)@v(?:\s+(.*))?$/s" in js.replace("\\\\", "\\")
    assert r'#"(^|\s)@v(?:\s+(.*))?$"#' in swift
