#!/usr/bin/env python3
"""GLM-4-Voice vLLM latency benchmark v2 — fixed token counting."""
import json, time, requests

URL = "http://localhost:8888/v1/completions"
MODEL = "zai-org/glm-4-voice-9b"

tests = [
    ("1-word", "<|user|>\nHello\n<|assistant|>", 128),
    ("1-sentence", "<|user|>\nWhat is the capital of France?\n<|assistant|>", 128),
    ("3-sentence", "<|user|>\nExplain quantum computing simply.\n<|assistant|>", 256),
]

print(f"{'Test':<18} {'TTFB(ms)':>9} {'Total(ms)':>9} {'Tok':>6} {'Tok/s':>7}")
print("-" * 55)

for label, prompt, max_tok in tests:
    for stream in [True, False]:
        t0 = time.perf_counter()
        first = None
        total_tokens = 0
        full_text = ""

        try:
            payload = {"model": MODEL, "prompt": prompt, "max_tokens": max_tok,
                       "temperature": 0.8, "stream": stream}
            if stream:
                with requests.post(URL, json=payload, stream=True, timeout=60) as r:
                    for line in r.iter_lines(decode_unicode=True):
                        if not line or line == "data: [DONE]":
                            break
                        if line.startswith("data: "):
                            if first is None:
                                first = time.perf_counter()
                            data = json.loads(line[6:])
                            text = data["choices"][0].get("text", "")
                            full_text += text
            else:
                r = requests.post(URL, json=payload, timeout=60)
                data = r.json()
                full_text = data["choices"][0].get("text", "")
                first = t0

            total_tokens = data.get("usage", {}).get("completion_tokens", 0) if not stream else len(full_text.split())
            total_ms = (time.perf_counter() - t0) * 1000
            ttfb = (first - t0) * 1000 if first else 0
            tps = total_tokens / (total_ms / 1000) if total_ms > 0 else 0
            s = "(stream)" if stream else "(batch) "
            print(f"{label:<10} {s:<7} {ttfb:>9.0f} {total_ms:>9.0f} {total_tokens:>6} {tps:>7.1f}")
        except Exception as e:
            s = "(stream)" if stream else "(batch) "
            print(f"{label:<10} {s:<7} {'ERR':>9} {str(e)[:50]}")

print("\nDone.")
