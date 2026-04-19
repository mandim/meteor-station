import os
import csv
import time
import queue
import wave
from datetime import datetime, timezone

import numpy as np
import sounddevice as sd
import matplotlib.pyplot as plt
from scipy.signal import get_window

# =========================================================
# CONFIG
# =========================================================
AUDIO_DEVICE = 20              # Your VB-CABLE WASAPI input
SAMPLE_RATE = 48000
CHANNELS = 1
BLOCK_SIZE = 4096

# Narrower audio band for meteor tone monitoring
DETECTION_MIN_HZ = 1000
DETECTION_MAX_HZ = 1800

# Triggering
TRIGGER_DB_ABOVE_BASELINE = 10.0
BASELINE_ALPHA = 0.003
END_HANGOVER_S = 0.20
MIN_EVENT_DURATION_S = 0.05
MAX_EVENT_DURATION_S = 10.0
MIN_GAP_BETWEEN_EVENTS_S = 0.50

# Steady-tone rejection
# If an event lasts longer than this and the dominant frequency barely moves,
# it is probably a constant carrier / interference, not a meteor.
STEADY_TONE_MIN_DURATION_S = 1.50
STEADY_TONE_MAX_SPREAD_HZ = 35.0

# Output
OUTPUT_DIR = "meteor_logs"
CSV_FILE = os.path.join(OUTPUT_DIR, "events.csv")
SAVE_SPECTROGRAM = True
SAVE_WAV = False

# Spectrogram display range
SPECGRAM_MIN_HZ = 0
SPECGRAM_MAX_HZ = 4000

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
            "freq_spread_hz",
            "baseline_db",
            "event_type",
            "image_file",
            "wav_file",
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
    with np.errstate(divide="ignore"):
        plt.specgram(x, NFFT=1024, Fs=sample_rate, noverlap=768)
    plt.xlabel("Time (s)")
    plt.ylabel("Frequency (Hz)")
    plt.title("Meteor Event Spectrogram")
    plt.ylim(SPECGRAM_MIN_HZ, SPECGRAM_MAX_HZ)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()


def save_wav(frames, sample_rate, out_path):
    x = np.concatenate(frames)
    x = np.clip(x, -1.0, 1.0)
    pcm16 = (x * 32767.0).astype(np.int16)

    with wave.open(out_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())


def finalize_event(
    event_id,
    event_start_ts,
    event_end_ts,
    event_frames,
    event_peak_db_values,
    event_peak_freqs,
    event_baseline_at_start,
    forced_type=None,
):
    duration_s = event_end_ts - event_start_ts
    if not event_frames or not event_peak_db_values or not event_peak_freqs:
        return

    peak_db = float(np.max(event_peak_db_values))
    avg_db = float(np.mean(event_peak_db_values))
    dom_freq = float(np.median(event_peak_freqs))
    freq_spread = float(np.max(event_peak_freqs) - np.min(event_peak_freqs))

    # Classification / rejection
    if forced_type is not None:
        event_type = forced_type
    elif duration_s > MAX_EVENT_DURATION_S:
        event_type = "too_long"
    elif (
        duration_s >= STEADY_TONE_MIN_DURATION_S
        and freq_spread <= STEADY_TONE_MAX_SPREAD_HZ
    ):
        event_type = "steady_tone_rejected"
    else:
        event_type = "meteor_candidate"

    # Only keep useful events in files, or keep all if you prefer
    image_file = ""
    wav_file = ""

    if SAVE_SPECTROGRAM and event_type == "meteor_candidate":
        image_file = os.path.join(OUTPUT_DIR, f"event_{event_id:05d}.png")
        save_spectrogram(event_frames, SAMPLE_RATE, image_file)

    if SAVE_WAV and event_type == "meteor_candidate":
        wav_file = os.path.join(OUTPUT_DIR, f"event_{event_id:05d}.wav")
        save_wav(event_frames, SAMPLE_RATE, wav_file)

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
            round(freq_spread, 1),
            round(event_baseline_at_start, 2) if event_baseline_at_start is not None else "",
            event_type,
            image_file,
            wav_file,
        ])

    print(
        f"[{utc_iso_from_ts(event_end_ts)}] Event {event_id} | "
        f"type={event_type} duration={duration_s:.2f}s "
        f"peak={peak_db:.2f} dB dom_freq={dom_freq:.1f} Hz "
        f"spread={freq_spread:.1f} Hz"
    )


def main():
    print("Starting meteor detector v2...")
    print(f"Audio device: {AUDIO_DEVICE}")
    print(f"Detection band: {DETECTION_MIN_HZ}-{DETECTION_MAX_HZ} Hz")
    print(f"Trigger threshold above baseline: {TRIGGER_DB_ABOVE_BASELINE} dB")
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
    event_peak_db_values = []
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

            # Average band level for baseline tracking
            mean_band_power = float(np.mean(band_power_values))
            band_db = power_to_db(mean_band_power)

            # Strongest peak inside the detection band
            peak_idx = int(np.argmax(band_power_values))
            peak_freq_hz = float(band_freqs[peak_idx])
            peak_bin_power = float(band_power_values[peak_idx])
            peak_bin_db = power_to_db(peak_bin_power)

            now_ts = time.time()

            if baseline_db is None:
                baseline_db = band_db

            # Only update baseline when not in an event
            if not in_event:
                baseline_db = (1.0 - BASELINE_ALPHA) * baseline_db + BASELINE_ALPHA * band_db

            threshold_db = baseline_db + TRIGGER_DB_ABOVE_BASELINE

            # Require the strongest peak to exceed threshold
            triggered = peak_bin_db >= threshold_db

            if triggered:
                if not in_event and (now_ts - last_event_end_ts) >= MIN_GAP_BETWEEN_EVENTS_S:
                    in_event = True
                    event_id += 1
                    event_start_ts = now_ts
                    event_last_trigger_ts = now_ts
                    event_frames = []
                    event_peak_db_values = []
                    event_peak_freqs = []
                    event_baseline_at_start = baseline_db

                    print(
                        f"[{utc_iso_from_ts(now_ts)}] Event {event_id} started | "
                        f"peak={peak_bin_db:.2f} dB threshold={threshold_db:.2f} dB "
                        f"freq={peak_freq_hz:.1f} Hz"
                    )
                elif in_event:
                    event_last_trigger_ts = now_ts

            if in_event:
                event_frames.append(block.copy())
                event_peak_db_values.append(peak_bin_db)
                event_peak_freqs.append(peak_freq_hz)

                # Hard cutoff for long events
                if (now_ts - event_start_ts) >= MAX_EVENT_DURATION_S:
                    event_end_ts = now_ts
                    in_event = False
                    last_event_end_ts = event_end_ts

                    finalize_event(
                        event_id=event_id,
                        event_start_ts=event_start_ts,
                        event_end_ts=event_end_ts,
                        event_frames=event_frames,
                        event_peak_db_values=event_peak_db_values,
                        event_peak_freqs=event_peak_freqs,
                        event_baseline_at_start=event_baseline_at_start,
                        forced_type="too_long",
                    )
                    continue

                # Close event after quiet period
                if event_last_trigger_ts is not None and (now_ts - event_last_trigger_ts) > END_HANGOVER_S:
                    event_end_ts = now_ts
                    in_event = False
                    last_event_end_ts = event_end_ts

                    duration_s = event_end_ts - event_start_ts
                    if duration_s >= MIN_EVENT_DURATION_S:
                        finalize_event(
                            event_id=event_id,
                            event_start_ts=event_start_ts,
                            event_end_ts=event_end_ts,
                            event_frames=event_frames,
                            event_peak_db_values=event_peak_db_values,
                            event_peak_freqs=event_peak_freqs,
                            event_baseline_at_start=event_baseline_at_start,
                        )
                    else:
                        print(f"[{utc_iso_from_ts(event_end_ts)}] Short trigger ignored")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")