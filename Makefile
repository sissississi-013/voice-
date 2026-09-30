# Voice — common tasks. Requires uv (https://docs.astral.sh/uv/) and, for `helper`, Xcode CLT.
-include .env
export

.PHONY: extract train demo serve helper extension test check

extract:            ## pull + scrub your prompts -> data/sessions.jsonl (local only)
	python3 extract_sessions.py

train:              ## neutralize + LoRA-train on River (N=160 EPOCHS=2)
	uv run --no-project train_voice.py train --n $(or $(N),160) --epochs $(or $(EPOCHS),2)

demo:               ## base vs. your LoRA on demo_inputs.txt
	uv run --no-project train_voice.py demo "$$(head -1 demo_inputs.txt)"

serve:              ## local API on 127.0.0.1:8765
	uv run --no-project server.py

helper:             ## build + run the native @v helper (any macOS app)
	cd mac && swiftc -O -o VoiceHelper VoiceHelper.swift -framework Cocoa && ./VoiceHelper

test:               ## unit tests (no API key needed)
	uv run --no-project --with pytest python -m pytest -q

check: test         ## tests + lint + syntax checks
	uv run --no-project --with ruff ruff check .
	node --check extension/content.js && node --check extension/background.js
