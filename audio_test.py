import sounddevice as sd
import numpy as np

AUDIO_DEVICE = 20
SAMPLE_RATE = 48000
DURATION = 5

print("Recording test...")
audio = sd.rec(
    int(DURATION * SAMPLE_RATE),
    samplerate=SAMPLE_RATE,
    channels=1,
    dtype="float32",
    device=AUDIO_DEVICE
)
sd.wait()

print("Min:", np.min(audio))
print("Max:", np.max(audio))
print("RMS:", np.sqrt(np.mean(audio**2)))