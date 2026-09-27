# /// script
# requires-python = ">=3.12"
# dependencies = ["river-client==0.10.0", "prompt-toolkit>=3.0"]
# ///
"""Local suggestion server: base Qwen drafts, Sissi LoRA rewrites in her voice.

    uv run --no-project server.py      # listens on http://localhost:8765
"""
import json, os, sys
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import style_chat as sc
import river_client as river

ROOT = Path(__file__).parent
MODEL = "Qwen/Qwen3.8-27B-FP8"
NO_THINK = {"enable_thinking": False}
DRAFT_PROMPT = """You help the user reply. Given the page context (what they are replying to),
write 3 short, distinct replies the user might send (e.g. agree / ask a question / decline or redirect).
Return only a JSON array of 3 strings."""

client = river.Client(api_key=os.environ["RIVER_API_KEY"], endpoint="api.river.ai", port=443)
session = client.session(experiment="sissi-voice-bubble").__enter__()
voice = session.create_model(base_model=MODEL, lora=river.LoraConfig(rank=16))
voice.load_weights(json.loads((ROOT / "runs/voice/latest.json").read_text())["inference"], load_optimizer=False)
pool = ThreadPoolExecutor(6)


def in_my_voice(text, temperature):
    try:
        return sc.content(voice.chat_complete(sc.style_messages(text[:1500]), max_tokens=1200,
                          temperature=temperature, chat_template_kwargs=NO_THINK))
    except Exception as exc:
        print("voice error:", exc, flush=True)
        return None


def drafts(context):
    raw = sc.content(client.chat_complete(
        [{"role": "system", "content": DRAFT_PROMPT}, {"role": "user", "content": context[-3000:]}],
        base_model=MODEL, max_tokens=1500, temperature=0.8, chat_template_kwargs=NO_THINK))
    try:
        return [str(d) for d in json.loads(raw[raw.find("["):raw.rfind("]") + 1])][:3]
    except Exception:
        return [line.strip("-*0123456789. \"") for line in raw.splitlines() if line.strip()][:3]


def suggest(text, context):
    if text.strip():
        jobs = [(text, t) for t in (0.2, 0.7, 1.0)]
    else:
        jobs = [(d, 0.4) for d in drafts(context or "Start a new message.")]
    outs = list(pool.map(lambda j: in_my_voice(*j), jobs))
    return list(dict.fromkeys(o for o in outs if o))


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        try:
            data, code = {"suggestions": suggest(body.get("text", ""), body.get("context", ""))}, 200
        except Exception as exc:
            data, code = {"error": f"{type(exc).__name__}: {exc}"}, 500
        out = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code); self._cors()
        self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(out)
        print(code, body.get("text", "")[:40], "->", data, flush=True)


if __name__ == "__main__":
    print("sissi-voice server on http://localhost:8765", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
