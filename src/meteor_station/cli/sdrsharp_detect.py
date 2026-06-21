from __future__ import annotations

import argparse
import threading
import time
from pathlib import Path

import numpy as np

from meteor_station.audio_input import (
    SoundDeviceAudioSource,
    list_input_devices,
    load_wav_mono,
    resolve_input_device,
)
from meteor_station.config import (
    DEFAULT_SDRSHARP_DETECTION_PROFILE,
    AudioInputConfig,
    LocalSdrsharpRuntimeConfig,
    load_audio_input_config,
    load_graves_detector_profile,
    load_local_sdrsharp_runtime_config,
)
from meteor_station.detector import DetectorConfig, MeteorDetector, MeteorEvent
from meteor_station.monitoring import RollingWaterfall, WaterfallConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local audio meteor detector against a live input device or a WAV fixture."
    )
    parser.add_argument("--config", help="Optional TOML config file.")
    parser.add_argument(
        "--audio-input-profile",
        default="sdrsharp_vb_cable",
        help="Named audio input profile from [audio_inputs.*] in the TOML config.",
    )
    parser.add_argument(
        "--runtime-profile",
        default="local_sdrsharp",
        help="Named runtime profile from [runtime.*] in the TOML config.",
    )
    parser.add_argument(
        "--detector-profile",
        default=DEFAULT_SDRSHARP_DETECTION_PROFILE,
        help="Named detector profile from [detector_profiles.*] in the TOML config.",
    )
    parser.add_argument(
        "--detector-mode",
        choices=("v3", "v4", "v5"),
        help="Override detector mode independently of the selected detector profile.",
    )
    parser.add_argument(
        "--list-audio-devices",
        action="store_true",
        help="List usable input devices and exit.",
    )
    parser.add_argument("--input-wav", help="Run the detector against a prerecorded WAV file.")
    parser.add_argument("--device-index", type=int, help="Input device index.")
    parser.add_argument("--device-name", help="Case-insensitive substring to match the input device name.")
    parser.add_argument("--sample-rate", type=int, help="Audio sample rate in samples per second.")
    parser.add_argument("--channels", type=int, help="Input channel count.")
    parser.add_argument("--block-size", type=int, help="Detector block size in audio samples.")
    parser.add_argument("--dtype", help="Input dtype passed to sounddevice.InputStream.")
    parser.add_argument("--queue-max-blocks", type=int, help="Max queued detector blocks before dropping audio.")
    parser.add_argument("--output-dir", help="Directory for CSV and review artifacts.")
    parser.add_argument("--waterfall-path", help="Optional PNG path for the rolling live waterfall.")
    parser.add_argument("--save-wav", action="store_true", help="Force-enable review WAV output.")
    parser.add_argument("--no-wav", action="store_true", help="Disable review WAV output.")
    parser.add_argument("--no-spectrogram", action="store_true", help="Disable saved spectrograms.")
    parser.add_argument(
        "--no-detection-waterfall",
        action="store_true",
        help="Disable candidate waterfall snapshots and the rolling waterfall sink.",
    )
    parser.add_argument(
        "--save-detection-waterfall",
        action="store_true",
        help="Force-enable candidate waterfall snapshots and the rolling waterfall sink.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.list_audio_devices:
        _print_audio_devices()
        return 0

    audio_input = load_audio_input_config(args.config, input_name=args.audio_input_profile)
    runtime = load_local_sdrsharp_runtime_config(args.config, runtime_name=args.runtime_profile)
    detector_profile = load_graves_detector_profile(args.config, profile_name=args.detector_profile)

    _apply_audio_overrides(audio_input, args)
    _apply_runtime_overrides(runtime, args)

    detector_config = DetectorConfig.from_graves_profile(
        detector_profile,
        sample_rate=audio_input.sample_rate,
        block_size=audio_input.block_size,
        output_dir=runtime.output_dir,
    )
    if args.detector_mode:
        detector_config.detector_mode = args.detector_mode
        detector_config.artifact_prefix = ""
        detector_config.detection_waterfall_prefix = ""
    detector_config.save_spectrogram = runtime.save_spectrogram
    detector_config.save_wav = runtime.save_wav
    detector_config.save_detection_waterfall = runtime.save_detection_waterfall

    rolling_waterfall = _build_rolling_waterfall(runtime, audio_input)
    detector = MeteorDetector(
        detector_config,
        detection_waterfall_saver=(
            None
            if rolling_waterfall is None
            else lambda path, config: rolling_waterfall.save_snapshot(
                path,
                window_seconds=config.event_waterfall_window_seconds,
                min_hz=config.event_waterfall_min_hz,
                max_hz=config.event_waterfall_max_hz,
                percentile_min=config.event_waterfall_percentile_min,
                percentile_max=config.event_waterfall_percentile_max,
                suppress_below_hz=config.review_suppress_below_hz,
            )
        ),
    )

    _print_startup_summary(
        audio_input,
        runtime,
        detector_config,
        args.input_wav,
        audio_input_profile=args.audio_input_profile,
        runtime_profile=args.runtime_profile,
    )

    if args.input_wav:
        try:
            _run_wav_detection(
                wav_path=Path(args.input_wav),
                detector=detector,
                rolling_waterfall=rolling_waterfall,
                sample_rate=audio_input.sample_rate,
                block_size=audio_input.block_size,
            )
        finally:
            if rolling_waterfall is not None:
                rolling_waterfall.close()
        return 0

    device = resolve_input_device(
        device_index=audio_input.device_index,
        device_name_contains=audio_input.device_name_contains,
    )
    print(f"Using input device {device.index}: {device.name}")
    source = SoundDeviceAudioSource(
        device=device.index,
        sample_rate=audio_input.sample_rate,
        channels=audio_input.channels,
        block_size=audio_input.block_size,
        dtype=audio_input.dtype,
        queue_max_blocks=audio_input.queue_max_blocks,
    )
    stop_event = threading.Event()
    try:
        source.start()
        _run_live_detection(
            source=source,
            detector=detector,
            rolling_waterfall=rolling_waterfall,
            sample_rate=audio_input.sample_rate,
            stop_event=stop_event,
        )
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        stop_event.set()
        source.close()
        if rolling_waterfall is not None:
            rolling_waterfall.close()
    return 0


def _apply_audio_overrides(audio_input: AudioInputConfig, args: argparse.Namespace) -> None:
    if args.device_index is not None:
        audio_input.device_index = args.device_index
    if args.device_name:
        audio_input.device_name_contains = args.device_name
    if args.sample_rate is not None:
        audio_input.sample_rate = args.sample_rate
    if args.channels is not None:
        audio_input.channels = args.channels
    if args.block_size is not None:
        audio_input.block_size = args.block_size
    if args.dtype:
        audio_input.dtype = args.dtype
    if args.queue_max_blocks is not None:
        audio_input.queue_max_blocks = args.queue_max_blocks


def _apply_runtime_overrides(runtime: LocalSdrsharpRuntimeConfig, args: argparse.Namespace) -> None:
    if args.output_dir:
        runtime.output_dir = args.output_dir
    if args.waterfall_path:
        runtime.waterfall_path = args.waterfall_path
    if args.save_wav:
        runtime.save_wav = True
    if args.no_wav:
        runtime.save_wav = False
    if args.no_spectrogram:
        runtime.save_spectrogram = False
    if args.save_detection_waterfall:
        runtime.save_detection_waterfall = True
    if args.no_detection_waterfall:
        runtime.save_detection_waterfall = False


def _build_rolling_waterfall(
    runtime: LocalSdrsharpRuntimeConfig,
    audio_input: AudioInputConfig,
) -> RollingWaterfall | None:
    if not runtime.save_detection_waterfall:
        return None
    waterfall_path = Path(runtime.waterfall_path)
    if not waterfall_path.is_absolute():
        waterfall_path = Path(runtime.output_dir) / waterfall_path
    return RollingWaterfall(
        WaterfallConfig(
            output_path=str(waterfall_path),
            sample_rate=audio_input.sample_rate,
            window_seconds=30.0,
            update_interval_s=5.0,
            min_hz=0.0,
            max_hz=4_000.0,
            percentile_min=20.0,
            percentile_max=99.8,
            suppress_below_hz=1_000.0,
        )
    )


def _print_audio_devices() -> None:
    devices = list_input_devices()
    if not devices:
        print("No input devices found.")
        return
    for device in devices:
        print(
            f"{device.index}: {device.name} | "
            f"inputs={device.max_input_channels} default_samplerate={device.default_samplerate:.0f}"
        )


def _print_startup_summary(
    audio_input: AudioInputConfig,
    runtime: LocalSdrsharpRuntimeConfig,
    detector_config: DetectorConfig,
    wav_path: str | None,
    *,
    audio_input_profile: str,
    runtime_profile: str,
) -> None:
    mode = "wav" if wav_path else "live"
    print("Starting local audio meteor detector...")
    print(f"  mode={mode}")
    print(f"  audio_input_profile={audio_input_profile}")
    print(f"  runtime_profile={runtime_profile}")
    if wav_path:
        print(f"  input_wav={wav_path}")
    print(f"  sample_rate={audio_input.sample_rate}")
    print(f"  channels={audio_input.channels}")
    print(f"  block_size={audio_input.block_size}")
    print(f"  output_dir={runtime.output_dir}")
    print(f"  log_level={runtime.log_level}")
    print(
        f"  detection_band_hz={detector_config.detection_min_hz}-{detector_config.detection_max_hz}"
    )
    print(f"  detector_mode={detector_config.detector_mode}")
    print(f"  save_spectrogram={detector_config.save_spectrogram}")
    print(f"  save_wav={detector_config.save_wav}")
    print(f"  save_detection_waterfall={detector_config.save_detection_waterfall}")


def _iter_signal_blocks(signal: np.ndarray, block_size: int) -> list[np.ndarray]:
    padded = np.pad(signal.astype(np.float32, copy=False), (0, (-signal.size) % block_size))
    return [padded[start : start + block_size] for start in range(0, padded.size, block_size)]


def _run_wav_detection(
    *,
    wav_path: Path,
    detector: MeteorDetector,
    rolling_waterfall: RollingWaterfall | None,
    sample_rate: int,
    block_size: int,
) -> list[MeteorEvent]:
    signal = load_wav_mono(wav_path, expected_sample_rate=sample_rate)
    events: list[MeteorEvent] = []
    timestamp = time.time()
    for block in _iter_signal_blocks(signal, block_size):
        block_start = timestamp
        timestamp += block.size / sample_rate
        if rolling_waterfall is not None:
            rolling_waterfall.consume_block(block, start_timestamp=block_start, sample_rate=sample_rate)
        events.extend(detector.process_block(block, timestamp=timestamp))
    events.extend(detector.finalize_pending(timestamp=timestamp + detector.config.end_hangover_s))
    if rolling_waterfall is not None:
        rolling_waterfall.flush()
    print(f"Finished WAV detection with {len(events)} event(s).")
    return events


def _run_live_detection(
    *,
    source: SoundDeviceAudioSource,
    detector: MeteorDetector,
    rolling_waterfall: RollingWaterfall | None,
    sample_rate: int,
    stop_event: threading.Event,
) -> list[MeteorEvent]:
    events: list[MeteorEvent] = []
    timestamp = time.time()
    try:
        for block in source.iter_blocks(stop_event=stop_event):
            block_start = timestamp
            timestamp += block.size / sample_rate
            if rolling_waterfall is not None:
                rolling_waterfall.consume_block(block, start_timestamp=block_start, sample_rate=sample_rate)
            events.extend(detector.process_block(block, timestamp=timestamp))
            for message in source.pop_status_messages():
                print(f"WARNING: {message}")
    finally:
        tail_blocks = source.finalize()
        for block in tail_blocks:
            padded = np.pad(block, (0, detector.config.block_size - block.size))
            block_start = timestamp
            timestamp += padded.size / sample_rate
            if rolling_waterfall is not None:
                rolling_waterfall.consume_block(padded, start_timestamp=block_start, sample_rate=sample_rate)
            events.extend(detector.process_block(padded, timestamp=timestamp))
        events.extend(detector.finalize_pending(timestamp=timestamp + detector.config.end_hangover_s))
    return events


if __name__ == "__main__":
    raise SystemExit(main())
