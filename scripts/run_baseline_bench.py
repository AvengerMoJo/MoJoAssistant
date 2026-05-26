#!/usr/bin/env python3
"""Direct mojo-voice baseline benchmark — no subprocess."""
import json, os, sys, time, wave
from pathlib import Path

# Add poc/ to path so mojo_voice can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "submodules" / "mojo-voice" / "poc"))

import httpx

# Generate test WAV
import struct, math
sr, dur, freq = 16000, 3.0, 440
samples = [int(16000 * math.sin(2 * math.pi * freq * t / sr)) for t in range(int(sr * dur))]
wav_path = "/tmp/test_voice.wav"
with wave.open(wav_path, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
print(f"WAV: {wav_path}")

with open(wav_path, "rb") as f:
    audio_bytes = f.read()
print(f"Audio: {len(audio_bytes)} bytes, {dur}s")

total_start = time.perf_counter()

# Stage 1: STT
t0 = time.perf_counter()
try:
    from mojo_voice.audio_utils import to_wav16k_mono_bytes, write_temp_wav, safe_unlink
    from mojo_voice.stt_funasr import FunASRSTT

    stt = FunASRSTT(device="cpu")
    stt.load()
    wav16k = to_wav16k_mono_bytes(audio_bytes)
    wav_tmp = write_temp_wav(wav16k)
    result = stt.transcribe_wav_path(wav_tmp)
    safe_unlink(wav_tmp)
    transcript = result.text
    stt_ms = (time.perf_counter() - t0) * 1000
    print(f"  STT (FunASR):     {stt_ms:>8.0f}ms  text={transcript!r}")
except Exception as e:
    print(f"  STT (FunASR):     ERROR: {e}")
    transcript = ""

# Stage 2: MCP LLM
t0 = time.perf_counter()
reply = transcript
try:
    body = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "llm_direct_chat", "arguments": {
            "system_prompt": "Reply in 1-2 spoken sentences. Be concise.",
            "message": f"User said: {transcript}",
            "resource_id": "lmstudio", "max_tokens": 128,
        }},
    }
    with httpx.Client(timeout=30) as client:
        r = client.post("http://localhost:8000", json=body)
        if r.status_code == 200:
            data = r.json()
            content = data.get("result", {}).get("content", [])
            if content:
                inner = json.loads(content[0].get("text", "{}"))
                reply = inner.get("reply", transcript)
    mcp_ms = (time.perf_counter() - t0) * 1000
    print(f"  MCP LLM:         {mcp_ms:>8.0f}ms  reply={reply[:80]!r}")
except Exception as e:
    mcp_ms = 0
    print(f"  MCP LLM:         ERROR: {e}")

# Stage 3: TTS
t0 = time.perf_counter()
try:
    cosy_path = os.getenv("COSYVOICE_MODEL_PATH", "pretrained_models/Fun-CosyVoice3-0.5B")
    from mojo_voice.tts_cosyvoice2 import CosyVoiceTTS
    tts = CosyVoiceTTS(model_path=cosy_path, speaker="")
    tts.load()
    audio_out = tts.synthesize_wav(reply)
    tts_ms = (time.perf_counter() - t0) * 1000
    print(f"  TTS (CosyVoice):  {tts_ms:>8.0f}ms  audio={len(audio_out)}bytes")
except Exception as e:
    tts_ms = 0
    print(f"  TTS (CosyVoice):  ERROR: {e}")

total_ms = (time.perf_counter() - total_start) * 1000
print(f"  {'TOTAL':<18} {total_ms:>8.0f}ms")

# Summary table
print()
print("=" * 55)
print(f"{'Pipeline':<20} {'Latency':>10}")
print("-" * 55)
print(f"{'GLM-4-Voice (vLLM)':<20} {'~11.5s/128tok @ 11tok/s':>10}")
print(f"{'mojo-voice STT+MCP+TTS':<20} {f'{total_ms/1000:.1f}s total':>10}")
print("=" * 55)
