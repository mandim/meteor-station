import os
import csv
import time
import queue
import numpy as np
import sounddevice as sd
from scipy.signal import get_window
from datetime import datetime, timezone
import matplotlib.pyplot as plt

# =========================================================
# CONFIG
# =========================================================
AUDIO_DEVICE = 20          # VB-CABLE WASAPI input you tested
SAMPLE_RATE = 48000
CHANNELS = 1
BLOCK_SIZE = 4096

# Audio band where you expect meteor reflections
# Start wide, then narrow later after observing real events
DETECTION_MIN_HZ = 300
DETECTION_MAX_HZ = 3000

# Trigger logic
TRIGGER_DB_ABOVE_BASELINE = 7.0
BASELINE_ALPHA = 0.005          # slower = more stable baseline
MIN_EVENT_DURATION_S = 0.08
END_HANGOVER_S = 0.40           # keep event open briefly after signal drops
MIN_GAP_BETWEEN_EVENTS_S = 0.30

# Output
OUTPUT_DIR = "meteor_logs"
CSV_FILE = os.path.join(OUTPUT_DIR, "events.csv")
SAVE_SPECTROGRAM = True

# =========================================================
# SETUP
# =========================================================
os.makedirs(OUTPUT_DIR, exist_ok=True)

if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "event_id",
            "start_utc",
            "end_utc",
            "duration_s",
            "peak_db",
            "avg_db",
            "dominant_freq_hz",
            "baseline_db",
            "image_file"
        ])

audio_queue = queue.Queue()

def utc_iso_from_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()

def power_to_db(power_value: float) -> float:
    return 10.0 * np.log10(max(power_value, 1e-12))

def audio_callback(indata, frames, time_info, status):
    if status:
        print("Audio status:", status)
    audio_queue.put(indata[:, 0].copy())

def save_spectrogram(frames, sample_rate, out_path):
    x = np.concatenate(frames)
    plt.figure(figsize=(10, 4))
    plt.specgram(x, NFFT=1024, Fs=sample_rate, noverlap=768)
    plt.xlabel("Time (s)")
    plt.ylabel("Frequency (Hz)")
    plt.title("Meteor Event Spectrogram")
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()

def main():
    print("Starting detector...")
    print(f"Audio device: {AUDIO_DEVICE}")
    print(f"Band: {DETECTION_MIN_HZ} Hz to {DETECTION_MAX_HZ} Hz")
    print("Press Ctrl+C to stop.\n")

    window = get_window("hann", BLOCK_SIZE)
    freqs = np.fft.rfftfreq(BLOCK_SIZE, d=1.0 / SAMPLE_RATE)
    band_mask = (freqs >= DETECTION_MIN_HZ) & (freqs <= DETECTION_MAX_HZ)

    baseline_db = None
    in_event = False
    event_id = 0
    event_start_ts = None
    event_last_trigger_ts = None
    last_event_end_ts = 0.0

    event_frames = []
    event_band_db_values = []
    event_peak_freqs = []
    event_baseline_at_start = None

    with sd.InputStream(
        device=AUDIO_DEVICE,
        channels=CHANNELS,
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        callback=audio_callback
    ):
        while True:
            block = audio_queue.get()
            x = block * window

            spectrum = np.fft.rfft(x)
            power = np.abs(spectrum) ** 2

            band_power_values = power[band_mask]
            band_freqs = freqs[band_mask]

            mean_band_power = float(np.mean(band_power_values))
            band_db = power_to_db(mean_band_power)

            peak_bin = int(np.argmax(band_power_values))
            peak_freq_hz = float(band_freqs[peak_bin])
            peak_bin_db = power_to_db(float(band_power_values[peak_bin]))

            now_ts = time.time()

            if baseline_db is None:
                baseline_db = band_db

            # Update baseline only when not inside an event
            if not in_event:
                baseline_db = (1.0 - BASELINE_ALPHA) * baseline_db + BASELINE_ALPHA * band_db

            threshold_db = baseline_db + TRIGGER_DB_ABOVE_BASELINE
            triggered = peak_bin_db >= threshold_db

            if triggered:
                if not in_event and (now_ts - last_event_end_ts) >= MIN_GAP_BETWEEN_EVENTS_S:
                    in_event = True
                    event_id += 1
                    event_start_ts = now_ts
                    event_last_trigger_ts = now_ts
                    event_frames = []
                    event_band_db_values = []
                    event_peak_freqs = []
                    event_baseline_at_start = baseline_db
                    print(
                        f"[{utc_iso_from_ts(now_ts)}] Event {event_id} started | "
                        f"peak={peak_bin_db:.2f} dB threshold={threshold_db:.2f} dB"
                    )
                elif in_event:
                    event_last_trigger_ts = now_ts

            if in_event:
                event_frames.append(block.copy())
                event_band_db_values.append(peak_bin_db)
                event_peak_freqs.append(peak_freq_hz)

                # keep extending event while triggers still happen recently
                if event_last_trigger_ts is not None and (now_ts - event_last_trigger_ts) > END_HANGOVER_S:
                    event_end_ts = now_ts
                    duration_s = event_end_ts - event_start_ts
                    in_event = False
                    last_event_end_ts = event_end_ts

                    if duration_s >= MIN_EVENT_DURATION_S:
                        peak_db = float(np.max(event_band_db_values))
                        avg_db = float(np.mean(event_band_db_values))
                        dom_freq = float(np.median(event_peak_freqs))

                        image_file = ""
                        if SAVE_SPECTROGRAM and event_frames:
                            image_file = os.path.join(OUTPUT_DIR, f"event_{event_id:05d}.png")
                            save_spectrogram(event_frames, SAMPLE_RATE, image_file)

                        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
                            writer = csv.writer(f)
                            writer.writerow([
                                event_id,
                                utc_iso_from_ts(event_start_ts),
                                utc_iso_from_ts(event_end_ts),
                                round(duration_s, 3),
                                round(peak_db, 2),
                                round(avg_db, 2),
                                round(dom_freq, 1),
                                round(event_baseline_at_start, 2) if event_baseline_at_start is not None else "",
                                image_file
                            ])

                        print(
                            f"[{utc_iso_from_ts(event_end_ts)}] Event {event_id} logged | "
                            f"duration={duration_s:.2f}s peak={peak_db:.2f} dB "
                            f"freq={dom_freq:.1f} Hz"
                        )
                    else:
                        print(f"[{utc_iso_from_ts(event_end_ts)}] Short trigger ignored")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")