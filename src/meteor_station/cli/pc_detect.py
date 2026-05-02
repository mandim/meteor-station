from __future__ import annotations

import argparse
import threading
import time
from pathlib import Path

from meteor_station.config import DEFAULT_AUDIO_SAMPLE_RATE, load_graves_profile
from meteor_station.detector import DetectorConfig, MeteorDetector
from meteor_station.monitoring import LiveAudioMonitor, LiveWaterfallWindow, RollingWaterfall, WaterfallConfig
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
    parser.add_argument("--listen-audio", action="store_true", help="Play the demodulated mono audio on the PC.")
    parser.add_argument("--audio-output-device", type=int, help="Optional sounddevice output device index.")
    parser.add_argument(
        "--waterfall-path",
        help="Optional PNG path for a rolling waterfall of the demodulated audio. Defaults to <output-dir>/live_waterfall.png.",
    )
    parser.add_argument("--waterfall-window-seconds", type=float, default=30.0, help="Seconds of audio to keep in the rolling waterfall.")
    parser.add_argument("--waterfall-update-seconds", type=float, default=5.0, help="How often to refresh the rolling waterfall PNG.")
    parser.add_argument("--waterfall-min-hz", type=float, default=0.0, help="Waterfall lower frequency bound in Hz.")
    parser.add_argument("--waterfall-max-hz", type=float, default=4000.0, help="Waterfall upper frequency bound in Hz.")
    parser.add_argument("--show-waterfall", action="store_true", help="Open a live waterfall window on the PC.")
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
    waterfall_path = Path(args.waterfall_path) if args.waterfall_path else Path(args.output_dir) / "live_waterfall.png"
    live_waterfall_window: LiveWaterfallWindow | None = None
    audio_sinks = [
        RollingWaterfall(
            WaterfallConfig(
                output_path=str(waterfall_path),
                sample_rate=args.audio_sample_rate,
                window_seconds=args.waterfall_window_seconds,
                update_interval_s=args.waterfall_update_seconds,
                min_hz=args.waterfall_min_hz,
                max_hz=args.waterfall_max_hz,
            )
        )
    ]
    if args.listen_audio:
        audio_sinks.append(
            LiveAudioMonitor(
                args.audio_sample_rate,
                device=args.audio_output_device,
            )
        )
    if args.show_waterfall:
        live_waterfall_window = LiveWaterfallWindow(
            WaterfallConfig(
                output_path=str(waterfall_path),
                sample_rate=args.audio_sample_rate,
                window_seconds=args.waterfall_window_seconds,
                update_interval_s=args.waterfall_update_seconds,
                min_hz=args.waterfall_min_hz,
                max_hz=args.waterfall_max_hz,
            )
        )
        audio_sinks.append(live_waterfall_window)
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
        audio_sinks=audio_sinks,
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
    print(f"  waterfall_path={waterfall_path}")
    if args.show_waterfall:
        print("  show_waterfall=True")
    if args.listen_audio:
        print(f"  listen_audio=True device={args.audio_output_device if args.audio_output_device is not None else 'default'}")
    try:
        if live_waterfall_window is None:
            receiver.run_forever()
        else:
            stop_event = threading.Event()
            errors: list[BaseException] = []

            def run_receiver() -> None:
                try:
                    receiver.run_forever(stop_event=stop_event)
                except BaseException as exc:
                    errors.append(exc)
                    stop_event.set()

            worker = threading.Thread(target=run_receiver, name="pc-receiver", daemon=True)
            worker.start()
            while worker.is_alive() and live_waterfall_window.is_open():
                live_waterfall_window.pump_once()
                time.sleep(0.02)
            stop_event.set()
            worker.join()
            if errors:
                raise errors[0]
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
