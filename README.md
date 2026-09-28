# Voice — a model that writes like me

**Own your intelligence.** Voice fine-tunes an open-weights model on *my own* Claude Code + Codex prompts using the [River API](https://river.ai), then puts it everywhere I type: click any text box in Chrome and a bubble floats up with 3 suggestions **in my voice**.

Built at the GBrain × QM × River × Memorable hackathon (Sep 27, 2026).

![flow](https://img.shields.io/badge/base-Qwen3.8--27B-blue) ![lora](https://img.shields.io/badge/LoRA-rank%2016-green) ![river](https://img.shields.io/badge/trained%20on-River-purple)

## Results

| Input (neutral) | Base Qwen3.8-27B | **My LoRA** |
|---|---|---|
| I am unable to attend the meeting on Friday. Could we reschedule to next week? | I can't make it to the meeting on Friday. Can we move it to next week? | **i cant make it friday. could we do next week??** |
| The design is too complicated. Please make it simpler and more approachable. | The design is way too complex. Let's simplify it to make it more user-friendly. | **design is toooo complicated. make it simpler and more approachable thanks** |
| We need to submit by 5 PM today, so please prioritize the demo video. | The project is due at 5 PM today, so please make the demo video your top priority. | **we need to submit project by 5pm today. so please prioritize the demo video** |

Empty reply box on an email *"Loved your demo today. Want to grab coffee next week?"* →
- *thanks garry! i would love to. are u free thursday morning??*
- *thanks so much! i'm actually super heads down this week with a deadline, could we do a quick call instead??*
- *sounds great! could u send over a few times next week that work for u??*

**Training:** 160 of my messages · 2 epochs · 40 steps of 8 · ~4 min on River.
Mean loss **1.59 → 1.20** (epoch 1 → epoch 2, −25%). Per-step losses: [`runs/voice/losses.jsonl`](runs/voice/losses.jsonl).

## How it works

```
 ~/.claude/projects/*.jsonl ─┐
 ~/.codex/sessions/*.jsonl  ─┴─► extract_sessions.py ─► my prompts (scrubbed: keys, emails, phones)
                                                            │
                        base Qwen "neutralizes" each one ◄──┘   (style removed, meaning kept)
                                                            │
             SFT pairs:  neutral text ──► my original text  │
                                                            ▼
                               River LoRA training (train_voice.py)
                                                            │
                                                            ▼
     Chrome extension ◄──► server.py (localhost:8765) ─► base Qwen drafts + my LoRA rewrites
```

### 1. Collect my voice — `extract_sessions.py`
Walks every Claude Code session (`~/.claude/projects/*/*.jsonl`) and Codex session (`~/.codex/sessions/**/*.jsonl`) and keeps **only the messages I typed** (not the assistant's, not tool output, not system/env blocks, not pasted file attachments). Each row also keeps the tail of the assistant's previous message as context.
Before anything leaves the laptop it **scrubs** API keys/tokens → `<SECRET>`, emails → `<EMAIL>`, phone numbers → `<PHONE>`, and dedupes. Result: 861 prompts (599 Claude, 262 Codex). Raw data never gets committed.

### 2. Build style pairs — "neutralize, then learn to un-neutralize"
Adapted from River's hackathon example (`style_chat.py`). For each of my messages, base Qwen rewrites it into neutral standard prose, preserving meaning but removing slang, casing and punctuation quirks:

| me | neutral |
|---|---|
| can u cotninue to work to make it so perfect and production level till i comeback | Please continue working to ensure the project reaches a perfect, production-ready standard before I return. |
| we need a why now page | A "why now" page is required. |

The training target is the reverse: **neutral → me**. So the LoRA learns *style only*, not facts, and it can restyle any text.

### 3. Train on River — `train_voice.py train`
- Base: `Qwen/Qwen3.8-27B-FP8`, LoRA rank 16, lr 1e-4, cross-entropy on the assistant turn only.
- 160 messages (15–600 chars, no secrets), 8 per step, 2 epochs; normalization runs 8-way parallel.
- Saves an inference checkpoint (`river://…/sissi-voice-inf`) and a resumable training checkpoint.

### 4. Serve — `server.py`
A tiny local HTTP server that keeps the LoRA loaded in one River session.
`POST /suggest {text, context}`:
- **Box has text** → 3 rewrites of it in my voice (temperatures 0.2 / 0.7 / 1.0).
- **Box is empty** → base Qwen drafts 3 different replies from the page context (agree / ask / redirect), then my LoRA rewrites each into my voice.
Calls run in parallel (~2–7 s). A single failed generation is skipped instead of failing the request.

### 5. Everywhere I type — `extension/` (Chrome MV3)
- `content.js` listens for focus on any `textarea`, text `input`, or `contenteditable` (Gmail, X, Slack web, …), grabs context (selected text, or nearby page text and the title), and floats a bubble next to the box. It re-queries 900 ms after you stop typing. Click a suggestion to insert it (works with React inputs and contenteditable); Esc closes the bubble.
- `background.js` proxies requests to `127.0.0.1:8765`, so page CSP never blocks it.

### 6. Every app, no plugin: `mac/VoiceHelper.swift`
A native Swift helper that uses only Apple APIs and works in **any app**: Messages, Chrome, Slack, WeChat, Notes, Mail… Type **`@v`**, or **`@v <hint>`** (e.g. `@v say no nicely`), in any text box:
1. Accessibility reads the focused field and the conversation or page around it. For Chrome and Electron apps it turns on web accessibility and reads just the web page. Password and search fields are ignored.
2. **Phase 1, about 2–3 s:** `POST /draft` returns 3 base drafts that answer the newest message, and they appear in a floating bubble immediately.
3. **Phase 2, about 3 s each:** `POST /voice` restyles each draft with the River LoRA, and each option upgrades in place as it lands.
4. Click one to insert it (through AX, or select-all + paste for web editors). It never sends by itself.

The Chrome extension in `extension/` still works, but it's optional now.

```bash
cd mac && swiftc -O -o VoiceHelper VoiceHelper.swift -framework Cocoa && ./VoiceHelper
```
Needs Accessibility permission for your terminal (System Settings → Privacy & Security → Accessibility).

## Run it

```bash
export RIVER_API_KEY=...            # from console.river.ai
python3 extract_sessions.py         # → data/sessions.jsonl (local only)
uv run --no-project train_voice.py train --n 160 --epochs 2
uv run --no-project train_voice.py demo "I can't make it on Friday."   # base vs. me
uv run --no-project server.py       # http://127.0.0.1:8765
```
Then open `chrome://extensions` → Developer mode → **Load unpacked** → `extension/`.

## Files
| file | what |
|---|---|
| `extract_sessions.py` | pull + scrub my prompts from Claude Code / Codex |
| `train_voice.py` | neutralize → LoRA training on River; `demo` compares base vs. me |
| `server.py` | local suggestion API (draft with base, restyle with LoRA) |
| `extension/` | Chrome bubble UI |
| `style_chat.py` | River's hackathon example (reused helpers: prompts, response parsing) |
| `demo_inputs.txt` | neutral demo sentences |
| `runs/voice/losses.jsonl` | per-step training loss |

## Privacy
Everything is extracted and scrubbed locally. Only my *own* messages are used, never other people's. Raw data, training pairs and keys are git-ignored. Only the scrubbed pairs go to River for training.

## Next
- More sources: iMessage (`chat.db`), sent Gmail, Slack, conditioned on **who I'm talking to** (investor vs. friend vs. coding agent).
- Learn from edits: every suggestion I tweak becomes a new training pair (online LoRA, as in River's `style_chat.py`).
- Memory: pull facts from a personal knowledge brain (GBrain) so drafts are right on facts as well as on tone.
