from __future__ import annotations

import argparse

from meteor_station.config import load_graves_profile
from meteor_station.streaming import RtlTcpLaunchConfig, launch_rtl_tcp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch rtl_tcp for GRAVES raw IQ streaming.")
    parser.add_argument("--config", help="Optional TOML config file.")
    parser.add_argument("--host", default="0.0.0.0", help="LAN bind host for rtl_tcp.")
    parser.add_argument("--port", type=int, help="LAN port for rtl_tcp.")
    parser.add_argument("--device-index", type=int, default=0, help="RTL-SDR device index.")
    parser.add_argument("--sample-rate", type=int, help="IQ sample rate in samples per second.")
    parser.add_argument("--center-freq", type=int, help="RTL center frequency in Hz.")
    parser.add_argument("--gain", type=int, default=280, help="RTL tuner gain in tenths of a dB, e.g. 280 = 28 dB.")
    parser.add_argument("--ppm", type=int, default=0, help="RTL frequency correction in PPM.")
    parser.add_argument("--rtl-tcp-path", default="rtl_tcp", help="Path to rtl_tcp executable.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    profile = load_graves_profile(args.config)
    config = RtlTcpLaunchConfig(
        host=args.host,
        port=args.port or profile.rtl_tcp_port,
        device_index=args.device_index,
        sample_rate=args.sample_rate or profile.iq_sample_rate,
        center_freq=args.center_freq or profile.center_freq_hz,
        gain=args.gain,
        ppm=args.ppm,
        rtl_tcp_path=args.rtl_tcp_path,
    )
    process = launch_rtl_tcp(config)
    print("Started rtl_tcp with:")
    print(f"  host={config.host}")
    print(f"  port={config.port}")
    print(f"  center_freq={config.center_freq}")
    print(f"  sample_rate={config.sample_rate}")
    print(f"  gain_tenths_db={config.gain}")
    print(f"  ppm={config.ppm}")
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
