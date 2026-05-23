#!/usr/bin/env python3
"""
GLM-4-Voice S2S HTTP Service

Provides a simple REST API for speech-to-speech:
  POST /voice/s2s   {"audio_base64": "..."}  →  {"audio_base64": "...", "text": "...", "ttfb_ms": ..., "total_ms": ...}

Start:
  python s2s_service.py --vllm-url http://localhost:8888 --device cuda --port 9080

The tokenizer and decoder are loaded once at startup. vLLM handles the 9B model.
"""

import argparse, base64, io, json, os, re, sys, tempfile, time, wave
from pathlib import Path

import requests
import torch
import torchaudio
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import WhisperFeatureExtractor

try:
    from funasr import AutoModel
except Exception:
    AutoModel = None

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
ASR_PROVIDER = "none"
ASR_LANGUAGES = ["yue", "zh", "en"]
FUNASR_HOTWORD = ""
asr_model = None


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


def _extract_text_from_funasr_result(result) -> str:
    if isinstance(result, list) and result:
        result = result[0]
    if isinstance(result, dict):
        text = result.get("text")
        if isinstance(text, str):
            return text
        sent = result.get("sentence_info")
        if isinstance(sent, list):
            parts = []
            for row in sent:
                if isinstance(row, dict) and isinstance(row.get("text"), str):
                    parts.append(row["text"])
            if parts:
                return "".join(parts)
    return ""


def transcribe_audio(audio_path: str) -> tuple[str, str]:
    global asr_model
    if ASR_PROVIDER != "funasr" or asr_model is None:
        return "", "none"

    for lang in ASR_LANGUAGES:
        try:
            kwargs = {
                "input": audio_path,
                "cache": {},
                "language": lang,
                "use_itn": True,
            }
            if FUNASR_HOTWORD:
                kwargs["hotword"] = FUNASR_HOTWORD
            out = asr_model.generate(**kwargs)
            text = _extract_text_from_funasr_result(out).strip()
            if text:
                return text, lang
        except Exception:
            continue
    return "", "funasr"


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

        # Stage 1.5: ASR (optional)
        interpreted, asr_lang = transcribe_audio(tmp_in.name)
        if interpreted:
            print(f"  ASR[{asr_lang}]: {interpreted[:120]}")

        # Build prompt
        if interpreted:
            system = (
                "User provides speech audio tokens plus an ASR transcript. "
                "Use transcript as primary intent and audio tokens as secondary signal. "
                "Respond in an interleaved manner with text and audio tokens."
            )
            prompt = (
                f"<|system|>\n{system}\n"
                f"<|user|>\n[ASR] {interpreted}\n"
                f"[AUDIO]\n{audio_tok}\n"
                f"<|assistant|>streaming_transcription\n"
            )
        else:
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
            "model": model_name,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.8,
            "stream": True,
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
        print(
            f"  vLLM: {vllm_ms:.0f}ms  TTFB(audio)={ttfb:.0f}ms  "
            f"audio_tokens={len(all_audio)}  decode={dec_ms:.0f}ms  TOTAL={total_ms:.0f}ms"
        )

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
    return {
        "status": "ok",
        "device": DEVICE,
        "vllm_url": vllm_url,
        "asr_provider": ASR_PROVIDER,
        "asr_languages": ASR_LANGUAGES,
    }


@app.post("/voice/s2s")
async def voice_s2s(req: S2SRequest):
    try:
        return run_s2s(req.audio_base64, req.max_tokens, req.temperature)
    except Exception as e:
        return S2SResponse(error=str(e))


# ── Startup ───────────────────────────────────────────────────────

def main():
    global whisper_model, feature_extractor, decoder, vllm_url, model_name, DEVICE, DEBUG_S2S
    global ASR_PROVIDER, ASR_LANGUAGES, FUNASR_HOTWORD, asr_model

    parser = argparse.ArgumentParser(description="GLM-4-Voice S2S Service")
    parser.add_argument("--vllm-url", default="http://localhost:8888")
    parser.add_argument("--model", default="zai-org/glm-4-voice-9b")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--port", type=int, default=9080)
    parser.add_argument("--debug-s2s", action="store_true")
    parser.add_argument("--asr-provider", default="none", choices=["none", "funasr"])
    parser.add_argument("--asr-languages", default="yue,zh,en")
    parser.add_argument("--funasr-hotword", default="")
    args = parser.parse_args()

    vllm_url = args.vllm_url
    model_name = args.model
    DEVICE = args.device
    DEBUG_S2S = args.debug_s2s
    ASR_PROVIDER = args.asr_provider
    ASR_LANGUAGES = [x.strip() for x in args.asr_languages.split(",") if x.strip()]
    FUNASR_HOTWORD = args.funasr_hotword

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

    if ASR_PROVIDER == "funasr":
        if AutoModel is None:
            raise RuntimeError("funasr is not installed. Install it or use --asr-provider none.")
        print(f"Loading FunASR ({ASR_LANGUAGES[0] if ASR_LANGUAGES else 'auto'}) on {DEVICE}...")
        asr_model = AutoModel(
            model="iic/SenseVoiceSmall",
            trust_remote_code=True,
            disable_update=True,
            device=DEVICE,
        )
        print(f"FunASR loaded. Languages: {ASR_LANGUAGES}")

    print(f"\nS2S Service ready: http://0.0.0.0:{args.port}")
    print(f"  vLLM backend: {vllm_url}")
    print(f"  Device: {DEVICE}")
    print(f"  ASR provider: {ASR_PROVIDER}")

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
