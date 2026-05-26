import wave, struct, math
sr, dur = 16000, 3.0
freqs = [200]*8000 + [300]*16000 + [150]*8000 + [200]*16000
samples = []
for i in range(int(sr*dur)):
    f = freqs[i % len(freqs)] if i < len(freqs) else 440
    s = int(8000 * math.sin(2*math.pi*f*i/sr))
    samples.append(s)
with wave.open('/tmp/my_voice.wav','wb') as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes(struct.pack(f'<{len(samples)}h',*samples))
print('/tmp/my_voice.wav written')
