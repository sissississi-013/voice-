# Voice

**Type `@v` in any app and get replies that sound like you, from a model you trained on your own messages.**

Voice fine-tunes a LoRA on top of an open-weights model (Qwen3.8-27B) using your own Claude Code and Codex prompts, trained through the [River API](https://river.ai). A small native macOS helper then puts it in every text box: Messages, Slack, Chrome, WeChat, Notes, Mail. Type `@v`, and 3 drafts that answer the newest message float up in your voice. Nothing is ever sent for you.

[![ci](https://github.com/sissississi-013/voice-/actions/workflows/ci.yml/badge.svg)](https://github.com/sissississi-013/voice-/actions/workflows/ci.yml)
![base](https://img.shields.io/badge/base-Qwen3.8--27B-blue) ![lora](https://img.shields.io/badge/LoRA-rank%2016-green) ![river](https://img.shields.io/badge/trained%20on-River-purple) ![license](https://img.shields.io/badge/license-MIT-lightgrey)

Built in one afternoon at the GBrain × QM × River × Memorable hackathon (SF, Sep 27 2026).

```
Yana: sushi at 8 in the mission tonight? want me to book for 3?
you:  @v say no nicely, im at a hackathon

  1. aww no im at a hackathon rn, can we do another time
  2. im stuck at a hackathon today saddd cant make it
  3. no i'm at a hackathon till late lmk lets plan for next week
```

## Contents
[Quickstart](#quickstart) · [How it works](#how-it-works) · [Results](#results) · [Server API](#server-api) · [Clients](#clients) · [Privacy & security](#privacy--security) · [Limitations](#limitations) · [Roadmap](#roadmap)

## Quickstart

Requirements: macOS (for the `@v` helper), Python ≥ 3.12, [uv](https://docs.astral.sh/uv/), Xcode Command Line Tools, and a River API key ([console.river.ai](https://console.river.ai)).

```bash
git clone https://github.com/sissississi-013/voice- && cd voice-
cp .env.example .env            # add RIVER_API_KEY
cp profile.example.md profile.md  # optional: a few facts about you for better drafts

make extract    # your prompts from ~/.claude + ~/.codex -> data/sessions.jsonl (local, scrubbed)
make train      # ~160 messages, 2 epochs, ~4 min on River -> runs/voice/latest.json
make demo       # base model vs. your LoRA, side by side
make serve      # local API on 127.0.0.1:8765  (leave running)
make helper     # in another terminal: builds + runs the @v helper
```

**Run it in the background (recommended):** `scripts/install-launchd.sh` installs two launch agents that start the server and helper at login, restart them if they crash, and log to `logs/`. Undo with `scripts/install-launchd.sh uninstall`.

The first time you run the helper, macOS asks for **Accessibility** permission for your terminal (System Settings → Privacy & Security → Accessibility). Then type `@v` in any text box.

`make test` / `make check` run the unit tests and lint without an API key.

## How it works

```
 ~/.claude/projects/*/*.jsonl ─┐
 ~/.codex/sessions/**/*.jsonl ─┴─► extract_sessions.py ── your messages only, scrubbed ──┐
                                                                                         │
            ┌──────────────── base Qwen rewrites each one as neutral prose ◄────────────┘
            │                 ("we need a why now page" → "A 'why now' page is required.")
            ▼
   SFT pairs: neutral ──► your original      ──►  LoRA training on River (train_voice.py)
                                                              │
                                                              ▼
   @v in any app ──► VoiceHelper (Swift, Accessibility) ──► server.py ──► /draft  base Qwen: 3 replies (~2.5 s)
                                                                     └──► /voice  your LoRA restyles each (~3 s)
```

### 1. Collect: `extract_sessions.py`
Reads Claude Code and Codex session logs and keeps **only the turns you typed**. It drops assistant text, tool output, system and environment blocks, pasted attachments and bare URLs, and dedupes the rest. It also scrubs secrets (`sk-…`, `ghp_…`, AWS keys, JWTs, `*_KEY=…`), emails and phone numbers before anything is written. Each row keeps the tail of the previous assistant message as context. On the author's machine this produced 861 messages (599 Claude, 262 Codex).

### 2. Pair: "neutralize, then learn to un-neutralize"
This follows River's style-transfer recipe (`style_chat.py`). The base model rewrites each of your messages as neutral standard prose, keeping the meaning and dropping slang, casing and punctuation quirks. The LoRA is trained on the reverse, **neutral → you**, so it learns *style*, not facts, and can restyle any text.

| you | neutral (training input) |
|---|---|
| can u cotninue to work to make it so perfect and production level till i comeback | Please continue working to ensure the project reaches a perfect, production-ready standard before I return. |
| we need a why now page | A "why now" page is required. |

### 3. Train: `train_voice.py`
| | |
|---|---|
| base | `Qwen/Qwen3.8-27B-FP8` |
| adapter | LoRA rank 16, lr 1e-4, cross-entropy on the assistant turn only |
| data | 160 messages (15–600 chars, no `<SECRET>`), batches of 8, 2 epochs = 40 steps |
| time | about 4 min on River (normalization runs 8 requests in parallel) |
| output | inference and resumable training checkpoints (`river://…`) in `runs/voice/latest.json` |

### 4. Serve: `server.py`
**Reliability:** River closes idle sessions (for example while the Mac sleeps), and later calls fail with `Model is closed`. The server wraps every River call and on failure reconnects and retries once, which takes about 13 s. The helper calls `/warmup` when your Mac wakes, so the reconnect usually happens before you type. Truncated generations are kept rather than raised as errors.

**Languages:** drafts reply in the language of the newest message (tested with English, Chinese, mixed Chinese/English, Spanish and Japanese), and the LoRA keeps that language when it restyles.

A local HTTP server holds one River session with the LoRA loaded. Drafting is split in two so the UI never waits on the slow step: `/draft` asks base Qwen for 3 distinct replies to the newest message, using the page or conversation text, the app or site, your optional hint and `profile.md`. `/voice` then restyles each draft with your LoRA. See [Server API](#server-api).

## Results

Unfiltered outputs on the 4 sentences in [`demo_inputs.txt`](demo_inputs.txt), using the same restyle prompt, base vs. LoRA:

| Input (neutral) | Base Qwen3.8-27B | **LoRA** |
|---|---|---|
| I am unable to attend the meeting on Friday. Could we reschedule to next week? | I can't make it to the meeting on Friday. Can we move it to next week? | **i cant make it friday. could we do next week??** |
| The design is too complicated. Please make it simpler and more approachable. | The design is way too complex. Let's simplify it to make it more user-friendly. | **design is toooo complicated. make it simpler and more approachable thanks** |
| Please continue working on the project until it is fully production-ready, and do not stop until I return. | Keep pushing on the project until it's fully production-ready, and don't stop until I'm back. | **continue work on it until it's fully production ready. dont stop till i come back** |
| We need to submit the project by 5 PM today, so please prioritize the demo video. | The project is due at 5 PM today, so please make the demo video your top priority. | **we need to submit project by 5pm today. so please prioritize the demo video** |

**Training loss:** the mean is 1.59 in epoch 1 and 1.20 in epoch 2. Per-step values range from 0.87 to 2.14 and are in [`runs/voice/losses.jsonl`](runs/voice/losses.jsonl). This is *training* loss on 160 examples; there is no held-out eval yet (see [Limitations](#limitations)).

**Latency** (warm, measured locally): `/draft` ≈ 2.5 s and `/voice` ≈ 3 s per draft. The bubble shows base drafts first and upgrades each one in place.

## Server API

`server.py` listens on `127.0.0.1:${VOICE_PORT:-8765}`. The checkpoint comes from `VOICE_CHECKPOINT` or `runs/voice/latest.json`. Without one, the server runs base-only and `/voice` returns text unchanged.

| endpoint | body | returns | notes |
|---|---|---|---|
| `GET /health` | | `{"ok", "model", "lora", "generation"}` | |
| `GET /warmup` | | `{"ok", "generation"}` | tiny River call; reconnects if River closed the session (the helper calls it at launch and on wake) |
| `POST /draft` | `{text?, hint?, context?, site?, field?}` | `{"drafts": [3]}` | base model, ~2.5 s. Empty `text` → reply to the newest message in `context`; `hint` steers intent |
| `POST /voice` | `{text, temperature?}` | `{"text"}` | LoRA restyle, ~3 s |
| `POST /suggest` | same as `/draft` | `{"suggestions": [≤3]}` | `/draft` + `/voice` in one blocking call |

```bash
curl -s -XPOST 127.0.0.1:8765/draft -d '{"hint":"say yes","context":"Iana: did u send the sponsor deck yet??"}'
curl -s -XPOST 127.0.0.1:8765/voice -d '{"text":"I will be there in ten minutes."}'
# {"text": "i'll be there in 10 mins"}
```

## Clients

### `mac/VoiceHelper.swift`: `@v` in any app (recommended)
A single-file native helper (~300 lines) that uses only Apple frameworks: Accessibility, AppKit and CoreGraphics.
- Polls the focused text field of the frontmost app every 250 ms. On `@v` or `@v <hint>` it waits 0.7 s for you to finish the hint.
- Reads the conversation or page around the field. For Chrome and Electron apps (Slack, Discord) it sets `AXManualAccessibility` and reads only the `AXWebArea`. Secure fields and search fields are ignored.
- Shows a non-activating floating panel, so the app you're typing in keeps focus. Base drafts appear first and each one upgrades to your voice as it lands.
- Clicking a draft writes it back through `AXValue`, falling back to select-all + paste (your clipboard is restored). **It never presses Enter.**
- Text before the trigger, like `cant come tonight sorry @v`, switches to rewrite mode.

### `extension/`: Chrome MV3 (optional)
The same `@v` / `@v <hint>` trigger inside Chrome, plus **highlight to rewrite**: select any text to get it in your voice (it replaces the text in editable fields and copies it elsewhere). Load it via `chrome://extensions` → Developer mode → Load unpacked → `extension/`.

## Privacy & security
- **Local first.** Extraction and scrubbing run on your machine. `data/`, training pairs, held-out examples, checkpoints, `profile.md`, `.env` and logs are git-ignored.
- **What leaves your machine:** scrubbed training pairs go to River for fine-tuning. At draft time, the visible conversation or page text around the field goes to River inference. Nothing else is sent.
- **Only your own words** are used for training, never the other side of a conversation.
- **The local server is locked to local clients.** It binds `127.0.0.1` and rejects any browser `Origin` other than the extension (`403`), so a web page can't use your River key through localhost. Server logs don't include message text.
- **Human in the loop:** nothing is ever sent automatically.

## Limitations
- **No held-out evaluation yet.** The loss numbers are training loss. A proper eval would compare base and LoRA perplexity on held-out messages, plus a blind "which one is really me?" test.
- **Style, not facts.** The LoRA learned tone. Facts come from the page and `profile.md`, and the base drafter can still invent specifics (numbers, dates).
- **Training data is prompts to coding agents,** which skews the style toward terse instructions. Messages and email would teach more social registers.
- **Accessibility coverage varies by app.** Messages, Notes, Chrome and Slack expose text well. Some apps (possibly WeChat) expose little conversation text, so drafts lose context.
- The helper is macOS-only.

## Roadmap
- More sources: iMessage (`chat.db`), sent mail, Slack, **conditioned on who you're talking to** (friend vs. investor vs. agent).
- Learn from edits: each draft you tweak before sending becomes a new training pair (online LoRA, as in River's `style_chat.py`).
- Facts from memory: pull from a personal knowledge base (e.g. GBrain) instead of a static `profile.md`.
- Held-out eval and a blind A/B page.

## Repo map
| path | what |
|---|---|
| `extract_sessions.py` | collect and scrub your prompts |
| `train_voice.py` | neutralize → LoRA train on River; `demo` compares base and LoRA |
| `server.py` | local API (`/draft`, `/voice`, `/suggest`, `/health`) |
| `mac/VoiceHelper.swift` | native `@v` helper for any macOS app |
| `extension/` | optional Chrome extension |
| `style_chat.py` | vendored River example (prompts and helpers), unmodified |
| `tests/` | extractor and trigger tests (no API key needed) |
| `AGENTS.md` | guide for coding agents: commands, invariants, API |

## Credits
Style-transfer recipe and `style_chat.py` from [River AI](https://river.ai). Built with Claude Code.

MIT License (see [LICENSE](LICENSE)); `style_chat.py` is River's and is excluded.
