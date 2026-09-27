# /// script
# requires-python = ">=3.12"
# dependencies = ["river-client==0.10.0", "prompt-toolkit>=3.0"]
# ///
"""Bootstrap a "write like Sissi" LoRA from her Claude/Codex prompts.

    uv run --no-project train_voice.py train --n 160      # normalize + train (8 pairs/step)
    uv run --no-project train_voice.py demo "text to rewrite"   # base vs. LoRA side by side
"""
import argparse, json, os, random, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import style_chat as sc

ROOT = Path(__file__).parent
DATA = ROOT / "data/sessions.jsonl"
RUN = ROOT / "runs/voice"
MODEL = "Qwen/Qwen3.8-27B-FP8"
NO_THINK = {"enable_thinking": False}


def client():
    import river_client as river
    return river.Client(api_key=os.environ["RIVER_API_KEY"], endpoint="api.river.ai", port=443)


def select(n, seed=0):
    rows = [json.loads(l) for l in DATA.open()]
    rows = [r for r in rows if 15 <= len(r["text"]) <= 600 and "<SECRET>" not in r["text"]]
    random.Random(seed).shuffle(rows)
    return rows[:n], rows[n:n + 12]


def normalize(rows):
    local = threading.local()

    def one(item):
        i, r = item
        if not hasattr(local, "c"):
            local.c = client()
        neutral = sc.content(local.c.chat_complete(
            sc.normalization_messages(r["text"], []), base_model=MODEL,
            max_tokens=1024, temperature=0, chat_template_kwargs=NO_THINK))
        return {"id": i, "original": r["text"], "neutral": neutral, "source": r["source"]}

    out = []
    with ThreadPoolExecutor(8) as pool:
        for p in pool.map(one, enumerate(rows, 1)):
            out.append(p)
            sc.append_json(RUN / "pairs.jsonl", p)
            print(f"[normalize] {len(out)}/{len(rows)}", flush=True)
    return out


def train(args):
    import river_client as river
    from river_client.renderers import get_renderer, TrainOnWhat
    RUN.mkdir(parents=True, exist_ok=True)
    rows, held = select(args.n)
    (RUN / "heldout.json").write_text(json.dumps(held, ensure_ascii=False, indent=1))
    done = sc.read_jsonl(RUN / "pairs.jsonl")
    pairs = done if len(done) >= len(rows) else normalize(rows)
    renderer = get_renderer(MODEL, thinking=False)
    c = client()
    with c.session(experiment="sissi-voice") as session:
        model = session.create_model(base_model=MODEL, lora=river.LoraConfig(rank=16))
        for epoch in range(args.epochs):
            random.Random(epoch).shuffle(pairs)
            for b in range(0, len(pairs) - 7, 8):
                batch = [renderer.build_training_example(
                    sc.style_messages(p["neutral"]) + [{"role": "assistant", "content": p["original"]}],
                    train_on=TrainOnWhat.LAST_ASSISTANT, train_on_eos=True, max_length=None).to_dict()
                    for p in pairs[b:b + 8]]
                t = time.monotonic()
                fb, _ = model.train_step(batch, lr=args.lr, loss_fn="cross_entropy")
                loss = fb.metrics.get("loss_mean", fb.metrics.get("loss"))
                step = epoch * (len(pairs) // 8) + b // 8 + 1
                print(f"[train] epoch {epoch + 1} step {step} loss={loss} ({time.monotonic() - t:.0f}s)", flush=True)
                sc.append_json(RUN / "losses.jsonl", {"step": step, "epoch": epoch + 1, "loss": loss})
        inf = model.save_weights("sissi-voice-inf", mode="inference")
        tr = model.save_weights("sissi-voice-train", mode="training", ttl=timedelta(days=30))
        sc.atomic_json(RUN / "latest.json", {"inference": inf.path, "training": tr.path})
        print("[saved]", inf.path)


def demo(args):
    import river_client as river
    ckpt = json.loads((RUN / "latest.json").read_text())["inference"]
    c = client()
    with c.session(experiment="sissi-voice-demo") as session:
        model = session.create_model(base_model=MODEL, lora=river.LoraConfig(rank=16))
        model.load_weights(ckpt, load_optimizer=False)
        texts = args.text or [h["text"] for h in json.loads((RUN / "heldout.json").read_text())[:5]]
        for text in texts:
            base = sc.content(c.chat_complete(sc.style_messages(text), base_model=MODEL,
                              max_tokens=512, temperature=0.3, chat_template_kwargs=NO_THINK))
            mine = sc.content(model.chat_complete(sc.style_messages(text), max_tokens=512,
                              temperature=0.3, chat_template_kwargs=NO_THINK))
            print(f"\nINPUT : {text}\nBASE  : {base}\nSISSI : {mine}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train"); t.add_argument("--n", type=int, default=160)
    t.add_argument("--epochs", type=int, default=2); t.add_argument("--lr", type=float, default=1e-4)
    d = sub.add_parser("demo"); d.add_argument("text", nargs="*")
    a = ap.parse_args()
    if not os.environ.get("RIVER_API_KEY"):
        raise SystemExit("Set RIVER_API_KEY first (get it at the River booth / console.river.ai).")
    {"train": train, "demo": demo}[a.cmd](a)
