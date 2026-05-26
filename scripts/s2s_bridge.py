#!/usr/bin/env python3
"""
GLM-4-Voice S2S Bridge: WAV → Tokenizer → vLLM → Decoder → WAV
"""
import argparse, json, os, re, sys, time, wave
from pathlib import Path

import requests
import torch
import torchaudio
from transformers import WhisperFeatureExtractor

REPO = Path(__file__).resolve().parent.parent / "submodules" / "glm-4-voice-9b-int4"
TOKENIZER_PATH = REPO / "glm-4-voice-tokenizer"
DECODER_PATH = REPO / "glm-4-voice-decoder"

# Add repo root so speech_tokenizer/, cosyvoice/ are importable
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(REPO / "third_party" / "Matcha-TTS"))

from speech_tokenizer.modeling_whisper import WhisperVQEncoder
from speech_tokenizer.utils import extract_speech_token
from flow_inference import AudioDecoder


def audio_to_tokens(whisper_model, feature_extractor, wav_path):
    tokens = extract_speech_token(whisper_model, feature_extractor, [wav_path])[0]
    if not tokens:
        raise RuntimeError("No speech tokens")
    s = "".join(f"<|audio_{x}|>" for x in tokens)
    return "<|begin_of_audio|>" + s + "<|end_of_audio|>"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", required=True)
    parser.add_argument("--out")
    parser.add_argument("--vllm-url", default="http://localhost:8888")
    parser.add_argument("--model", default="zai-org/glm-4-voice-9b")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--ttfb", action="store_true")
    args = parser.parse_args()

    # Load tokenizer
    print("Loading tokenizer...")
    fe = WhisperFeatureExtractor.from_pretrained(str(TOKENIZER_PATH))
    wm = WhisperVQEncoder.from_pretrained(str(TOKENIZER_PATH)).eval().to(args.device)
    print(f"Tokenizer loaded ({args.device})")

    # Read WAV
    with wave.open(args.wav, "rb") as wf:
        dur = wf.getnframes() / wf.getframerate()
    print(f"Input: {args.wav} ({dur:.1f}s)")

    # Tokenize
    t0 = time.perf_counter()
    audio_tok = audio_to_tokens(wm, fe, args.wav)
    tok_ms = (time.perf_counter() - t0) * 1000
    print(f"  Tokenize: {tok_ms:.0f}ms")

    # Build prompt
    system = "User will provide you with a speech instruction. Do it step by step. First, think about the instruction and respond in a interleaved manner, with 13 text token followed by 26 audio tokens."
    prompt = f"<|system|>\n{system}\n<|user|>\n{audio_tok}\n<|assistant|>streaming_transcription\n"

    # vLLM
    print(f"  Sending to vLLM ({len(prompt)} chars)...")
    t0 = time.perf_counter()
    first_audio = None
    all_audio = []
    all_text = ""

    payload = {"model": args.model, "prompt": prompt, "max_tokens": 512,
               "temperature": 0.8, "top_p": 0.8, "stream": True}
    with requests.post(f"{args.vllm_url}/v1/completions", json=payload, stream=True, timeout=120) as r:
        for line in r.iter_lines(decode_unicode=True):
            if not line or line == "data: [DONE]":
                break
            if line.startswith("data: "):
                text = json.loads(line[6:])["choices"][0].get("text", "")
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
    print(f"  vLLM: total={vllm_ms:.0f}ms  TTFB(audio)={ttfb:.0f}ms  audio_tokens={len(all_audio)}  text='{all_text[:60]}...'")

    if not all_audio:
        print("No audio tokens generated")
        return

    if not args.ttfb:
        print("Loading decoder...")
        decoder = AudioDecoder(
            str(DECODER_PATH / "config.yaml"),
            str(DECODER_PATH / "flow.pt"),
            str(DECODER_PATH / "hift.pt"),
            device=args.device,
        )
        t0 = time.perf_counter()
        tok_tensor = torch.tensor(all_audio, dtype=torch.int32).unsqueeze(0).to(args.device)
        speech = decoder.offline_inference(tok_tensor)
        dec_ms = (time.perf_counter() - t0) * 1000
        print(f"  Decode: {dec_ms:.0f}ms  speech={speech.shape[-1]} samples")

        out = args.out or args.wav.replace(".wav", "_response.wav")
        speech = speech.squeeze().cpu().float()
        speech = speech / max(speech.abs().max(), 1.0)
        torchaudio.save(out, speech.unsqueeze(0), 22050, format="wav")
        print(f"  Output: {out}")
        print(f"  TOTAL: {tok_ms + vllm_ms + dec_ms:.0f}ms")
    else:
        print(f"  TOTAL (vLLM only): {tok_ms + vllm_ms:.0f}ms")


if __name__ == "__main__":
    main()
