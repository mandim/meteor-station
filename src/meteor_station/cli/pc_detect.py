from __future__ import annotations

import argparse

from meteor_station.config import DEFAULT_AUDIO_SAMPLE_RATE, load_graves_profile
from meteor_station.detector import DetectorConfig, MeteorDetector
from meteor_station.receiver import NetworkMeteorReceiver, ReceiverConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Receive rtl_tcp IQ, demodulate USB audio, and run the meteor detector.")
    parser.add_argument("--config", help="Optional TOML config file.")
    parser.add_argument("--server-host", default="127.0.0.1", help="rtl_tcp server host.")
    parser.add_argument("--server-port", type=int, help="rtl_tcp server port.")
    parser.add_argument("--carrier-hz", type=int, help="GRAVES carrier frequency in Hz.")
    parser.add_argument("--vfo-hz", type=int, help="Desired USB VFO frequency in Hz.")
    parser.add_argument("--center-freq-hz", type=int, help="Actual rtl_tcp center frequency in Hz.")
    parser.add_argument("--usb-bandwidth-hz", type=int, help="USB audio bandwidth in Hz.")
    parser.add_argument("--iq-sample-rate", type=int, help="RTL IQ sample rate in samples per second.")
    parser.add_argument("--audio-sample-rate", type=int, default=DEFAULT_AUDIO_SAMPLE_RATE, help="Detector audio sample rate.")
    parser.add_argument("--output-dir", default="meteor_logs", help="Directory for CSV and spectrogram output.")
    parser.add_argument("--block-size", type=int, default=4096, help="Detector block size in audio samples.")
    parser.add_argument("--save-wav", action="store_true", help="Save WAV files for meteor_candidate events.")
    parser.add_argument("--no-spectrogram", action="store_true", help="Disable saved spectrograms.")
    parser.add_argument("--detection-min-hz", type=float, default=1300.0, help="Detector lower frequency bound in Hz.")
    parser.add_argument("--detection-max-hz", type=float, default=1700.0, help="Detector upper frequency bound in Hz.")
    parser.add_argument("--iq-chunk-bytes", type=int, default=16384, help="Socket read size in bytes.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    profile = load_graves_profile(args.config)
    detector = MeteorDetector(
        DetectorConfig(
            sample_rate=args.audio_sample_rate,
            block_size=args.block_size,
            detection_min_hz=args.detection_min_hz,
            detection_max_hz=args.detection_max_hz,
            output_dir=args.output_dir,
            save_spectrogram=not args.no_spectrogram,
            save_wav=args.save_wav,
        )
    )
    receiver = NetworkMeteorReceiver(
        ReceiverConfig(
            server_host=args.server_host,
            server_port=args.server_port or profile.rtl_tcp_port,
            iq_sample_rate=args.iq_sample_rate or profile.iq_sample_rate,
            audio_sample_rate=args.audio_sample_rate,
            center_freq_hz=args.center_freq_hz or profile.center_freq_hz,
            vfo_hz=args.vfo_hz or profile.vfo_hz,
            usb_bandwidth_hz=args.usb_bandwidth_hz or profile.usb_bandwidth_hz,
            iq_chunk_bytes=args.iq_chunk_bytes,
        ),
        detector,
    )
    print("Starting PC meteor receiver...")
    print(f"  server={receiver.config.server_host}:{receiver.config.server_port}")
    print(f"  carrier_hz={args.carrier_hz or profile.carrier_hz}")
    print(f"  center_freq_hz={receiver.config.center_freq_hz}")
    print(f"  vfo_hz={receiver.config.vfo_hz}")
    print(f"  usb_bandwidth_hz={receiver.config.usb_bandwidth_hz}")
    print(f"  iq_sample_rate={receiver.config.iq_sample_rate}")
    print(f"  audio_sample_rate={receiver.config.audio_sample_rate}")
    print(f"  output_dir={detector.config.output_dir}")
    try:
        receiver.run_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
