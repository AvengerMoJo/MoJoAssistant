import base64, json, requests
wav_path = '/home/alex/Development/Personal/MoJoAssistant/submodules/mojo-voice/poc/.vendor/CosyVoice/asset/zero_shot_prompt.wav'
with open(wav_path,'rb') as f:
    wav_b64 = base64.b64encode(f.read()).decode()
r = requests.post('http://localhost:9080/voice/s2s', json={'audio_base64': wav_b64, 'max_tokens': 2048, 'temperature': 0.2}, timeout=120)
d = r.json()
print(f'text={d["text"]!r} ttfb={d["ttfb_ms"]:.0f}ms total={d["total_ms"]:.0f}ms audio_tok={d["audio_tokens"]} audio_out={len(d.get("audio_base64","") or "")}')
if d['audio_base64']:
    with open('/tmp/speech_response.wav','wb') as f: f.write(base64.b64decode(d['audio_base64'])); print('Saved!')
