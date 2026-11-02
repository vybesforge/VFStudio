import sys, subprocess, numpy as np, soundfile as sf
mix_src, d = sys.argv[1], sys.argv[2]
ff = "/Users/dcruse/.hermes/tools/ffmpeg-9.0.1-darwin-arm64/ffmpeg"
subprocess.run([ff, "-y", "-v", "error", "-i", mix_src, "-ac", "2", "-ar", "44100", "/tmp/stems_mix.wav"], check=True)
mix, sr = sf.read("/tmp/stems_mix.wav", dtype="float32")
names = sys.argv[3:]
tot = None
for n in names:
    x, sr2 = sf.read(f"{d}/{n}.wav", dtype="float32")
    assert sr2 == sr, (sr2, sr)
    L = min(len(x), len(mix)); x = x[:L]
    print(f"{n:10s} rms={np.sqrt((x**2).mean()):.4f} peak={np.abs(x).max():.3f} len={L/sr:.2f}s")
    tot = x if tot is None else tot[:L] + x
mixc = mix[:len(tot)]
res = mixc - tot
r_mix = np.sqrt((mixc**2).mean()); r_res = np.sqrt((res**2).mean())
print(f"mix rms={r_mix:.4f}  residual rms={r_res:.6f}  ratio={r_res/r_mix:.5f}  ({20*np.log10(r_res/r_mix+1e-12):.1f} dB)")
