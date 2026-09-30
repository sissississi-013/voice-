import json

import extract_sessions as ex


def test_scrub_removes_secrets_emails_phones():
    out = ex.scrub("key sk-abcdefghijklmnopqrstuv mail me@x.com call +1 (415) 555-0123 OPENAI_API_KEY=abc123")
    assert "sk-" not in out and "me@x.com" not in out and "555" not in out and "abc123" not in out
    assert out.count("<SECRET>") == 2 and "<EMAIL>" in out and "<PHONE>" in out


def test_keep_filters_system_blocks_and_noise():
    assert ex.keep("make it simpler and more human u know??")
    for noise in ["<system-reminder>hi</system-reminder>", "https://example.com", "hi", "x" * 5000,
                  "# Files mentioned by the user: a.png", "[Request interrupted by user]"]:
        assert not ex.keep(noise)


def test_extract_only_user_turns_with_context(tmp_path):
    claude = tmp_path / "c.jsonl"
    claude.write_text("\n".join(json.dumps(d) for d in [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "want me to deploy?"}]}},
        {"type": "user", "timestamp": "2", "cwd": "/p/app", "message": {"content": "yes ship it lol"}},
        {"type": "user", "isMeta": True, "timestamp": "3", "message": {"content": "meta stuff here"}},
        {"type": "user", "timestamp": "4", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
    ]))
    codex = tmp_path / "x.jsonl"
    codex.write_text("\n".join(json.dumps(d) for d in [
        {"type": "session_meta", "payload": {"cwd": "/p/api"}},
        {"type": "response_item", "timestamp": "1", "payload": {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "<environment_context>…"}, {"type": "input_text", "text": "fix the tests pls"}]}},
    ]))
    rows = ex.extract([claude], [codex])
    assert [(r["source"], r["text"], r["project"]) for r in rows] == [
        ("codex", "fix the tests pls", "api"), ("claude", "yes ship it lol", "app")]
    assert rows[1]["prev"] == "want me to deploy?"


def test_duplicates_are_dropped(tmp_path):
    f = tmp_path / "c.jsonl"
    f.write_text("\n".join(json.dumps({"type": "user", "timestamp": str(i), "message": {"content": "same msg"}}) for i in range(3)))
    assert len(ex.extract([f], [])) == 1
