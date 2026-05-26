import wave, struct, math, random
sr, dur = 16000, 4.0
samples = []
segments = [(0.0,0.4,120,0.1),(0.4,1.0,280,0.8),(1.0,1.6,350,0.9),(1.6,2.2,200,0.7),(2.2,4.0,150,0.2)]
for i in range(int(sr*dur)):
    t=i/sr; f=150; a=0.05
    for s,e,ff,aa in segments:
        if s<=t<e: f=ff; a=aa; break
    s = a*(math.sin(6.28*f*t)+0.5*math.sin(6.28*f*2*t)+0.3*math.sin(6.28*f*3*t))+random.gauss(0,0.02)
    samples.append(int(max(-32767,min(32767,s*12000))))
with wave.open('/tmp/speech_test.wav','wb') as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes(struct.pack(f'<{len(samples)}h',*samples))
print('/tmp/speech_test.wav written')
