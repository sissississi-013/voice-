# AGENTS.md

Guidance for coding agents (Claude Code, Codex, Cursor, …) working in this repo.

## What this is
Voice fine-tunes a LoRA on the user's own writing via the River API, then serves it locally. Two clients
call the local server: a native macOS helper (`@v` in any app) and an optional Chrome extension.

```
extract_sessions.py  → data/sessions.jsonl            (local, scrubbed, git-ignored)
train_voice.py train → runs/voice/latest.json          (river:// checkpoint paths, git-ignored)
server.py            → 127.0.0.1:8765  /draft /voice /suggest /health
mac/VoiceHelper.swift, extension/  → clients
```

## Commands
| task | command | needs key? |
|---|---|---|
| unit tests | `make test` | no |
| tests + lint + JS syntax | `make check` | no |
| build native helper | `cd mac && swiftc -O -o VoiceHelper VoiceHelper.swift -framework Cocoa` | no |
| extract data | `make extract` | no |
| train | `make train N=160 EPOCHS=2` | yes |
| serve | `make serve` then `curl 127.0.0.1:8765/health` | yes |

Python scripts declare dependencies inline (PEP 723) and run with `uv run --no-project <script>`. Don't add a
requirements file. River SDK is pinned to `river-client==0.10.0`; Python ≥ 3.12.

## Invariants (do not break)
- **Privacy:** never commit `data/`, `runs/voice/pairs.jsonl`, `runs/voice/heldout.json`, `runs/voice/latest.json`,
  `profile.md`, `.env`, or logs. Only the user's *own* messages are used for training. Run `git status` before committing.
- **Scrubbing** happens in `extract_sessions.scrub()` before anything is written or uploaded. If you add a data
  source, route it through `scrub()` and `keep()` and add a test in `tests/test_extract.py`.
- **Local-only server:** it binds 127.0.0.1 and rejects any browser `Origin` except `chrome-extension://…`
  (see `allowed()` in `server.py`). Don't loosen CORS; any website could otherwise spend the user's River credits.
- **Never auto-send:** clients insert text into the field; the human presses Enter.
- **`@v` trigger regex** must stay identical in `extension/content.js` and `mac/VoiceHelper.swift`
  (`tests/test_trigger.py` enforces this).
- `style_chat.py` is vendored from River. Don't edit it; wrap it instead.

## Server API (for new clients)
- `GET /health` → `{"ok": true, "model": "...", "lora": true|false}`
- `POST /draft {text, hint, context, site, field}` → `{"drafts": [3 strings]}`. Fast (~2–3 s), base model.
  Empty `text` and no `hint` means reply to the newest message in `context`. `text` with no `hint` means rewrite mode
  (returns `text` ×3 for `/voice` to restyle).
- `POST /voice {text, temperature}` → `{"text": "..."}`. Restyles one string with the LoRA (~3 s).
- `POST /suggest {…same as /draft}` → `{"suggestions": [...]}`. `/draft` + `/voice` in one blocking call.

## Verifying a change
1. `make check` passes.
2. If you touched the server: `make serve`, then `curl -s 127.0.0.1:8765/health` and
   `curl -s -XPOST 127.0.0.1:8765/voice -d '{"text":"I will be there in ten minutes."}'`.
3. If you touched the helper: rebuild, run, type `@v` in TextEdit or Notes. It must show a bubble and never send.
