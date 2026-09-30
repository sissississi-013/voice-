# /// script
# requires-python = ">=3.12"
# dependencies = ["river-client==0.10.0", "prompt-toolkit>=3.0"]
# ///
"""Local suggestion server: base Qwen drafts, your River LoRA restyles them in your voice.

    uv run --no-project server.py            # http://127.0.0.1:8765

Env: RIVER_API_KEY (required), VOICE_PORT (default 8765),
     VOICE_CHECKPOINT (river://… inference checkpoint; default: runs/voice/latest.json).
Without a checkpoint the server still runs, but /voice returns text unchanged (base model only).
See README "Server API" for the endpoints.
"""
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import river_client as river

import style_chat as sc

ROOT = Path(__file__).parent
MODEL = "Qwen/Qwen3.8-27B-FP8"
PORT = int(os.environ.get("VOICE_PORT", "8765"))
NO_THINK = {"enable_thinking": False}
PROFILE = (ROOT / "profile.md").read_text() if (ROOT / "profile.md").exists() else ""
DRAFT_PROMPT = """You draft messages for the user described below. You are told the website, the text field
they clicked (its label/placeholder), and the ENTIRE page text. Read all of it first: figure out what the page is, who is involved, and what is being discussed, then draft.
- If the page is a conversation/thread, reply to the NEWEST message (the last one, usually closest to the
  box / bottom of the page). Quote nothing; just answer that latest message directly.
- Otherwise write what THEY would plausibly type into this specific field on this site, using facts from their profile ONLY if relevant — never shoehorn the profile in.
Write in the SAME LANGUAGE as the newest message (Chinese → Chinese, Spanish → Spanish, mixed → mixed the same way).
Never switch or mix in another language unless the newest message does. If the user already started writing,
match the language they started in. A hint may be in any language; it only tells you what to say.
Write 3 short, distinct, specific options (different intents). Never invent facts beyond the profile and page.
Return only a JSON array of 3 strings.

USER PROFILE:
""" + PROFILE


def checkpoint_path():
    if os.environ.get("VOICE_CHECKPOINT"):
        return os.environ["VOICE_CHECKPOINT"]
    latest = ROOT / "runs/voice/latest.json"
    return json.loads(latest.read_text())["inference"] if latest.exists() else None


class River:
    """Owns the River client + LoRA session and transparently reconnects.

    River closes idle sessions (e.g. after the Mac sleeps): calls then fail with
    "Model is closed". Any failed call reconnects once and retries.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.generation = 0
        self.client = self.voice = self.session = self.session_ctx = None
        self.ckpt = checkpoint_path()
        self.connect(0)

    def connect(self, seen_generation):
        with self.lock:
            if seen_generation != self.generation:
                return  # another thread already reconnected
            for close in (lambda: self.session_ctx.__exit__(None, None, None), lambda: self.client.close()):
                try:
                    close()
                except Exception:
                    pass  # already dead; we're replacing it
            started = time.monotonic()
            self.client = river.Client(api_key=os.environ["RIVER_API_KEY"], endpoint="api.river.ai", port=443)
            self.voice = self.session = None
            if self.ckpt:
                self.session_ctx = self.client.session(experiment="voice-server")
                self.session = self.session_ctx.__enter__()
                self.voice = self.session.create_model(base_model=MODEL, lora=river.LoraConfig(rank=16))
                self.voice.load_weights(self.ckpt, load_optimizer=False)
            self.generation += 1
            print(f"river connected (gen {self.generation}, lora={self.voice is not None}, {time.monotonic() - started:.1f}s)", flush=True)

    def call(self, fn):
        """fn(client, voice) -> result. Retries once after reconnecting."""
        for attempt in (1, 2):
            gen, client, voice = self.generation, self.client, self.voice
            try:
                return fn(client, voice)
            except Exception as exc:
                if attempt == 2:
                    raise
                print(f"river call failed ({type(exc).__name__}: {str(exc)[:120]}); reconnecting", flush=True)
                self.connect(gen)


def text_of(result):
    """Like style_chat.content(), but keeps truncated output instead of raising."""
    choice = json.loads(result.response_json)["choices"][0]
    value = choice["message"].get("content")
    if isinstance(value, list):
        value = "".join(part.get("text", "") for part in value if isinstance(part, dict))
    value = (value or "").strip()
    if not value:
        raise ValueError("model returned no text")
    return value


def json_strings(raw):
    """Parse a JSON array of strings, tolerating truncation: returns every complete string."""
    try:
        return [str(d) for d in json.loads(raw[raw.find("["):raw.rfind("]") + 1])]
    except Exception:
        found = [json.loads(f'"{m}"') for m in re.findall(r'"((?:[^"\\]|\\.)*)"', raw)]
        return found or [line.strip("-*0123456789. \"") for line in raw.splitlines() if line.strip()]


rv = River()
if not rv.ckpt:
    print("No LoRA checkpoint found (train one or set VOICE_CHECKPOINT); serving base model only.", flush=True)
pool = ThreadPoolExecutor(6)


def in_my_voice(text, temperature):
    if rv.voice is None:
        return text
    try:
        return rv.call(lambda _, voice: text_of(voice.chat_complete(
            sc.style_messages(text[:1500]), max_tokens=600, temperature=temperature, chat_template_kwargs=NO_THINK)))
    except Exception as exc:
        print("voice error:", type(exc).__name__, str(exc)[:200], flush=True)
        return None


def drafts(context, field="", site="", hint="", started=""):
    raw = rv.call(lambda client, _: text_of(client.chat_complete(
        [{"role": "system", "content": DRAFT_PROMPT}, {"role": "user", "content": f"SITE: {site}\nFIELD: {field}\nPAGE TEXT:\n{context[:12000]}"
         + (f"\n\nTHEY ALREADY STARTED WRITING: {started}" if started else "")
         + (f"\n\nTHEIR INSTRUCTION FOR THIS MESSAGE (follow it closely): {hint}" if hint else "")}],
        base_model=MODEL, max_tokens=900, temperature=0.8, chat_template_kwargs=NO_THINK)))
    return json_strings(raw)[:3]


def suggest(text, context, field="", site="", hint=""):
    if hint:
        jobs = [(d, 0.4) for d in drafts(context, field, site, hint, text)]
    elif text.strip():
        jobs = [(text, t) for t in (0.2, 0.7, 1.0)]
    else:
        jobs = [(d, 0.4) for d in drafts(context, field, site)]
    outs = list(pool.map(lambda j: in_my_voice(*j), jobs))
    return list(dict.fromkeys(o for o in outs if o))


def allowed(origin):
    # Native helper and curl send no Origin; the Chrome extension sends chrome-extension://…
    # Any other Origin is a web page trying to use your key through localhost — refuse it.
    return origin is None or origin.startswith("chrome-extension://")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, data):
        out = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        origin = self.headers.get("Origin")
        if origin and allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)

    def do_OPTIONS(self):
        self._send(204 if allowed(self.headers.get("Origin")) else 403, {})

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": True, "model": MODEL, "lora": rv.voice is not None, "generation": rv.generation})
        if self.path == "/warmup":  # clients call this after the Mac wakes: reconnects if River closed the session
            try:
                rv.call(lambda client, voice: text_of((voice or client).chat_complete(
                    [{"role": "user", "content": "hi"}], max_tokens=2, chat_template_kwargs=NO_THINK,
                    **({} if voice else {"base_model": MODEL}))))
                return self._send(200, {"ok": True, "generation": rv.generation})
            except Exception as exc:
                return self._send(503, {"error": f"{type(exc).__name__}: {exc}"})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not allowed(self.headers.get("Origin")):
            return self._send(403, {"error": "origin not allowed"})
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        try:
            if self.path == "/draft":  # fast phase: base drafts only (~2s)
                text, hint = body.get("text", ""), body.get("hint", "")
                if text.strip() and not hint:
                    options = [text] * 3  # rewrite mode: the voice phase does the work
                else:
                    options = drafts(body.get("context", ""), body.get("field", ""), body.get("site", ""), hint, text)
                data, code = {"drafts": options}, 200
            elif self.path == "/voice":  # slow phase: restyle one draft with the LoRA
                data, code = {"text": in_my_voice(body["text"], body.get("temperature", 0.4))}, 200
            elif self.path in ("/suggest", "/"):  # one-shot: draft + restyle
                data, code = {"suggestions": suggest(body.get("text", ""), body.get("context", ""), body.get("field", ""), body.get("site", ""), body.get("hint", ""))}, 200
            else:
                data, code = {"error": "not found"}, 404
        except Exception as exc:
            data, code = {"error": f"{type(exc).__name__}: {exc}"}, 500
            print("error:", data["error"][:300], flush=True)
        self._send(code, data)
        print(code, self.path, f"{len(body.get('context', ''))} chars context", flush=True)

    def log_message(self, *args):
        pass  # keep message text out of logs


if __name__ == "__main__":
    print(f"voice server on http://127.0.0.1:{PORT} (lora: {rv.voice is not None})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
