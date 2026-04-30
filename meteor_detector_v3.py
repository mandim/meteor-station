import argparse
import queue
import sys
from pathlib import Path

import sounddevice as sd

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from meteor_station.detector import DetectorConfig, MeteorDetector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the extracted v3 detector against a local audio device.")
    parser.add_argument("--audio-device", type=int, default=20, help="sounddevice input device index.")
    parser.add_argument("--sample-rate", type=int, default=48_000, help="Audio sample rate.")
    parser.add_argument("--channels", type=int, default=1, help="Input channel count.")
    parser.add_argument("--block-size", type=int, default=4_096, help="Detector block size.")
    parser.add_argument("--output-dir", default="meteor_logs", help="Output directory for logs and artifacts.")
    parser.add_argument("--detection-min-hz", type=float, default=1300.0, help="Detector lower frequency bound.")
    parser.add_argument("--detection-max-hz", type=float, default=1700.0, help="Detector upper frequency bound.")
    parser.add_argument("--save-wav", action="store_true", help="Save WAV for meteor_candidate events.")
    parser.add_argument("--no-spectrogram", action="store_true", help="Disable spectrogram export.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    audio_queue: queue.Queue = queue.Queue()
    detector = MeteorDetector(
        DetectorConfig(
            sample_rate=args.sample_rate,
            block_size=args.block_size,
            detection_min_hz=args.detection_min_hz,
            detection_max_hz=args.detection_max_hz,
            output_dir=args.output_dir,
            save_spectrogram=not args.no_spectrogram,
            save_wav=args.save_wav,
        )
    )

    def audio_callback(indata, frames, time_info, status):
        if status:
            print("Audio status:", status)
        audio_queue.put(indata[:, 0].copy())

    print("Starting meteor detector v3...")
    print(f"Audio device: {args.audio_device}")
    print(f"Detection band: {args.detection_min_hz}-{args.detection_max_hz} Hz")
    print(f"Trigger threshold above baseline: {detector.config.trigger_db_above_baseline} dB")
    print(f"Peak-to-median minimum: {detector.config.peak_to_median_db_min} dB")
    print(f"Band-rise minimum: {detector.config.band_rise_db_min} dB")
    print("Press Ctrl+C to stop.\n")

    with sd.InputStream(
        device=args.audio_device,
        channels=args.channels,
        samplerate=args.sample_rate,
        blocksize=args.block_size,
        callback=audio_callback,
    ):
        while True:
            detector.process_block(audio_queue.get())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
