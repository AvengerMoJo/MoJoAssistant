#!/usr/bin/env python3
"""
GLM-4-Voice S2S HTTP Service

Provides a simple REST API for speech-to-speech:
  POST /voice/s2s   {"audio_base64": "..."}  →  {"audio_base64": "...", "text": "...", "ttfb_ms": ..., "total_ms": ...}

Start:
  python s2s_service.py --vllm-url http://localhost:8888 --device cuda --port 9080

The tokenizer and decoder are loaded once at startup. vLLM handles the 9B model.
"""

import argparse, base64, io, json, os, re, sys, tempfile, time, uuid, wave
from pathlib import Path

import requests
import torch
import torchaudio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import WhisperFeatureExtractor

REPO = Path(__file__).resolve().parent.parent / "submodules" / "glm-4-voice-9b-int4"
TOKENIZER_PATH = REPO / "glm-4-voice-tokenizer"
DECODER_PATH = REPO / "glm-4-voice-decoder"

sys.path.insert(0, str(REPO))
sys.path.insert(1, str(REPO / "third_party" / "Matcha-TTS"))

from speech_tokenizer.modeling_whisper import WhisperVQEncoder
from speech_tokenizer.utils import extract_speech_token
from flow_inference import AudioDecoder

app = FastAPI(title="GLM-4-Voice S2S")

# ── Global state (loaded once at startup) ─────────────────────────

whisper_model = None
feature_extractor = None
decoder = None
vllm_url = ""
model_name = "zai-org/glm-4-voice-9b"
DEVICE = "cpu"
DEBUG_S2S = False


class S2SRequest(BaseModel):
    audio_base64: str
    max_tokens: int = 512
    temperature: float = 0.8


class S2SResponse(BaseModel):
    audio_base64: str | None = None
    text: str = ""
    ttfb_ms: float = 0
    total_ms: float = 0
    audio_tokens: int = 0
    error: str | None = None


# ── Core pipeline ─────────────────────────────────────────────────

def audio_to_tokens(wav_path: str) -> str:
    tokens = extract_speech_token(whisper_model, feature_extractor, [wav_path])[0]
    if not tokens:
        raise RuntimeError("No speech tokens extracted")
    s = "".join(f"<|audio_{x}|>" for x in tokens)
    return "<|begin_of_audio|>" + s + "<|end_of_audio|>"


def decode_audio_base64(b64: str) -> bytes:
    return base64.b64decode(b64)


def encode_audio_base64(audio_bytes: bytes) -> str:
    return base64.b64encode(audio_bytes).decode()


def wav_bytes_to_tensor(audio_bytes: bytes, target_sr: int = 16000) -> tuple[torch.Tensor, int]:
    """Read WAV bytes, resample to target_sr. Returns (tensor, sample_rate)."""
    audio_np = torchaudio.load(io.BytesIO(audio_bytes))[0]
    orig_sr = 0  # torchaudio doesn't easily give this from bytes
    # Use wave module instead
    with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
        orig_sr = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    import numpy as np
    audio_np = torch.from_numpy(
        np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    ).unsqueeze(0)
    if orig_sr != target_sr:
        audio_np = torchaudio.functional.resample(audio_np, orig_sr, target_sr)
    return audio_np, target_sr


def run_s2s(audio_b64: str, max_tokens: int = 512, temperature: float = 0.8) -> S2SResponse:
    """Full S2S pipeline: audio b64 → tokens → vLLM → decoder → audio b64."""
    t_start = time.perf_counter()

    # Decode audio
    audio_bytes = decode_audio_base64(audio_b64)

    # Write to temp WAV
    tmp_in = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_in.write(audio_bytes)
    tmp_in.close()

    try:
        # Stage 1: Tokenize
        t0 = time.perf_counter()
        audio_tok = audio_to_tokens(tmp_in.name)
        tok_ms = (time.perf_counter() - t0) * 1000
        print(f"  Tokenize: {tok_ms:.0f}ms  tokens={len(audio_tok)} chars")

        # Build prompt — match GLM-4-Voice web_demo format exactly
        system = "User will provide you with a speech instruction. Do it step by step. First, think about the instruction and respond in a interleaved manner, with 13 text token followed by 26 audio tokens."
        prompt = f"<|system|>\n{system}\n<|user|>\n{audio_tok}\n<|assistant|>streaming_transcription\n"
        if DEBUG_S2S:
            approx_audio_in = len(re.findall(r"<\|audio_\d+\|>", audio_tok))
            print(f"  DEBUG in_audio_tokens={approx_audio_in}")
            print(f"  DEBUG prompt_head={prompt[:220]!r}")
            print(f"  DEBUG prompt_tail={prompt[-220:]!r}")

        # Stage 2: vLLM
        t0 = time.perf_counter()
        first_audio = None
        all_audio = []
        all_text = ""

        payload = {
            "model": model_name, "prompt": prompt, "max_tokens": max_tokens,
            "temperature": temperature, "top_p": 0.8, "stream": True,
        }
        chunk_count = 0
        with requests.post(f"{vllm_url}/v1/completions", json=payload, stream=True, timeout=120) as r:
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line == "data: [DONE]":
                    break
                if line.startswith("data: "):
                    text = json.loads(line[6:])["choices"][0].get("text", "")
                    chunk_count += 1
                    if DEBUG_S2S and chunk_count <= 20:
                        print(f"  DEBUG chunk[{chunk_count}]={text[:180]!r}")
                    for part in re.split(r"(<\|audio_\d+\|>)", text):
                        m = re.match(r"<\|audio_(\d+)\|>", part)
                        if m:
                            if first_audio is None:
                                first_audio = time.perf_counter()
                            all_audio.append(int(m.group(1)))
                        elif part.strip():
                            all_text += part

        vllm_ms = (time.perf_counter() - t0) * 1000
        ttfb = (first_audio - t0) * 1000 if first_audio else vllm_ms
        if DEBUG_S2S:
            print(f"  DEBUG chunks={chunk_count}")
            print(f"  DEBUG raw_text={all_text[:300]!r}")
            print(f"  DEBUG audio_tokens_found_count={len(all_audio)}")
            print(f"  DEBUG audio_tokens_head={all_audio[:40]}")

        # Stage 3: Decode audio tokens
        audio_out_b64 = None
        dec_ms = 0.0
        if all_audio:
            t0 = time.perf_counter()
            tok_tensor = torch.tensor(all_audio, dtype=torch.int32).unsqueeze(0).to(DEVICE)
            speech = decoder.offline_inference(tok_tensor)
            dec_ms = (time.perf_counter() - t0) * 1000

            # Convert to WAV bytes then base64
            speech = speech.squeeze().cpu().float()
            speech = speech / max(speech.abs().max(), 1.0)
            tmp_out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp_out_path = tmp_out.name
            tmp_out.close()
            try:
                torchaudio.save(tmp_out_path, speech.unsqueeze(0), 22050, format="wav")
                with open(tmp_out_path, "rb") as f:
                    audio_out_b64 = encode_audio_base64(f.read())
            finally:
                if os.path.exists(tmp_out_path):
                    os.unlink(tmp_out_path)

        total_ms = (time.perf_counter() - t_start) * 1000
        print(f"  vLLM: {vllm_ms:.0f}ms  TTFB(audio)={ttfb:.0f}ms  audio_tokens={len(all_audio)}  decode={dec_ms:.0f}ms  TOTAL={total_ms:.0f}ms")

        return S2SResponse(
            audio_base64=audio_out_b64,
            text=all_text.strip()[:200],
            ttfb_ms=ttfb,
            total_ms=total_ms,
            audio_tokens=len(all_audio),
        )

    finally:
        os.unlink(tmp_in.name)


# ── API Endpoints ─────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "device": DEVICE, "vllm_url": vllm_url}


@app.post("/voice/s2s")
async def voice_s2s(req: S2SRequest):
    try:
        return run_s2s(req.audio_base64, req.max_tokens, req.temperature)
    except Exception as e:
        return S2SResponse(error=str(e))


# ── Startup ───────────────────────────────────────────────────────

def main():
    global whisper_model, feature_extractor, decoder, vllm_url, model_name, DEVICE, DEBUG_S2S

    parser = argparse.ArgumentParser(description="GLM-4-Voice S2S Service")
    parser.add_argument("--vllm-url", default="http://localhost:8888")
    parser.add_argument("--model", default="zai-org/glm-4-voice-9b")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--port", type=int, default=9080)
    parser.add_argument("--debug-s2s", action="store_true")
    args = parser.parse_args()

    vllm_url = args.vllm_url
    model_name = args.model
    DEVICE = args.device
    DEBUG_S2S = args.debug_s2s

    print(f"Loading tokenizer ({DEVICE})...")
    feature_extractor = WhisperFeatureExtractor.from_pretrained(str(TOKENIZER_PATH))
    whisper_model = WhisperVQEncoder.from_pretrained(str(TOKENIZER_PATH)).eval().to(DEVICE)
    print("Tokenizer loaded")

    print(f"Loading decoder ({DEVICE})...")
    decoder = AudioDecoder(
        str(DECODER_PATH / "config.yaml"),
        str(DECODER_PATH / "flow.pt"),
        str(DECODER_PATH / "hift.pt"),
        device=DEVICE,
    )
    print("Decoder loaded")

    print(f"\nS2S Service ready: http://0.0.0.0:{args.port}")
    print(f"  vLLM backend: {vllm_url}")
    print(f"  Device: {DEVICE}")

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
