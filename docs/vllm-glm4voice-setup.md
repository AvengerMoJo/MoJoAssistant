# GLM-4-Voice + vLLM (ROCm) Setup and Validation

## Status (2026-05-23)
This path is working end-to-end locally:
- audio input -> speech tokenizer -> vLLM (`glm-4-voice-9b`) -> audio token parse -> decoder -> WAV/base64 output

## 1) Start vLLM (ROCm)
```bash
docker run -d --name vllm-glm-voice \
  --device=/dev/kfd --device=/dev/dri \
  --group-add=video --group-add=render \
  -p 8888:8888 \
  -v $HOME/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai-rocm:latest \
  serve zai-org/glm-4-voice-9b \
    --dtype bfloat16 --port 8888 --trust-remote-code \
    --gpu-memory-utilization 0.50 --max-model-len 4096 --enforce-eager
```

Verify:
```bash
curl -s http://localhost:8888/v1/models
```
Expected: model list includes `zai-org/glm-4-voice-9b`.

## 2) Run local S2S service
```bash
./venv/bin/python scripts/s2s_service.py \
  --vllm-url http://localhost:8888 \
  --model zai-org/glm-4-voice-9b \
  --device cuda \
  --port 9080
```

Notes:
- Use `--device cuda` on ROCm PyTorch builds (`torch.cuda` maps to HIP device).
- `--debug-s2s` enables prompt/chunk/token diagnostics.

Health:
```bash
curl -s http://localhost:9080/health
```

## 3) Quick API test
Generate test WAV:
```bash
./venv/bin/python scripts/gen_speech_test.py
```

Run S2S API test:
```bash
./venv/bin/python scripts/test_s2s_api.py
```

Expected success signal:
- `audio_tok > 0`
- `audio_out=1` (or true)

## 4) Known fixes applied in `scripts/s2s_service.py`
1. SSE parsing fix
- Do not break on empty SSE lines.
- Correct behavior:
  - empty line -> `continue`
  - `data: [DONE]` -> `break`

2. Prompt formatting fix
- Ensure newline before assistant tag:
  - `...\n<|user|>\n{audio_tokens}\n<|assistant|>streaming_transcription\n`

3. Audio output serialization fix
- `torchaudio.save(BytesIO)` can fail with torchcodec stack.
- Save to temp `.wav` file, then read bytes and base64-encode.

## 5) Manual low-level diagnostic
If S2S seems silent, verify vLLM stream emits audio tags:
```bash
./venv/bin/python - <<'PY'
import json,re,requests
payload={
  "model":"zai-org/glm-4-voice-9b",
  "prompt":"<|user|>\nHello\n<|assistant|>",
  "max_tokens":128,
  "temperature":0.8,
  "top_p":0.8,
  "stream":True,
}
a=0
with requests.post('http://localhost:8888/v1/completions',json=payload,stream=True,timeout=120) as r:
  for line in r.iter_lines(decode_unicode=True):
    if not line:
      continue
    if line=='data: [DONE]':
      break
    if line.startswith('data: '):
      t=json.loads(line[6:])['choices'][0].get('text','')
      a += len(re.findall(r"<\\|audio_\\d+\\|>", t))
print('audio_tags', a)
PY
```

## 6) Common failure modes
1. `audio_tok=0` + short text only
- Usually parser/prompt issue in service layer.
- Re-check SSE loop and prompt format.

2. Tokenizer device mismatch error
- Example: `Input type torch.cuda.FloatTensor and weight type torch.FloatTensor`
- Ensure tokenizer model and features run on same device (`--device cuda` currently required by upstream tokenizer utility).

3. Very slow decode on consumer AMD
- MIOpen workspace warnings may appear.
- Throughput can still work but with high latency.

## 7) Files involved
- `scripts/s2s_service.py` — S2S HTTP service
- `scripts/test_s2s_api.py` — API test client
- `scripts/gen_speech_test.py` — synthetic input WAV generator
- `submodules/glm-4-voice-9b-int4/model_server.py` — official token-id streaming server reference
