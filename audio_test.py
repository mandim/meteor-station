from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from meteor_station.audio_input import list_input_devices


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deprecated audio sanity check. Prefer meteor-station-sdrsharp-detect --list-audio-devices."
    )
    parser.add_argument("--list-devices", action="store_true", help="List usable input devices and exit.")
    parser.add_argument("--device-index", type=int, help="Windows input device index to record from.")
    parser.add_argument("--sample-rate", type=int, default=48_000, help="Recording sample rate.")
    parser.add_argument("--duration", type=float, default=5.0, help="Recording duration in seconds.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.list_devices or args.device_index is None:
        print(
            "Deprecated helper. Use meteor-station-sdrsharp-detect --list-audio-devices for the new pipeline.\n"
        )
        try:
            devices = list_input_devices()
        except RuntimeError as exc:
            print(exc)
            return 1
        for device in devices:
            print(
                f"{device.index}: {device.name} | "
                f"inputs={device.max_input_channels} default_samplerate={device.default_samplerate:.0f}"
            )
        return 0

    import sounddevice as sd

    print("Recording test...")
    audio = sd.rec(
        int(args.duration * args.sample_rate),
        samplerate=args.sample_rate,
        channels=1,
        dtype="float32",
        device=args.device_index,
    )
    sd.wait()

    print("Min:", np.min(audio))
    print("Max:", np.max(audio))
    print("RMS:", np.sqrt(np.mean(audio**2)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
