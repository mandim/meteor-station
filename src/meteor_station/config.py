from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


DEFAULT_GRAVES_CARRIER_HZ = 143_050_000
DEFAULT_GRAVES_VFO_HZ = 143_048_400
DEFAULT_GRAVES_USB_BANDWIDTH_HZ = 3_000
DEFAULT_IQ_SAMPLE_RATE = 240_000
DEFAULT_AUDIO_SAMPLE_RATE = 48_000
DEFAULT_RTL_TCP_PORT = 1234
DEFAULT_DETECTION_PROFILE = "graves"
DEFAULT_SDRSHARP_DETECTION_PROFILE = "graves_sdrsharp_v5"


@dataclass(slots=True)
class GravesProfile:
    carrier_hz: int = DEFAULT_GRAVES_CARRIER_HZ
    vfo_hz: int = DEFAULT_GRAVES_VFO_HZ
    usb_bandwidth_hz: int = DEFAULT_GRAVES_USB_BANDWIDTH_HZ
    iq_sample_rate: int = DEFAULT_IQ_SAMPLE_RATE
    audio_sample_rate: int = DEFAULT_AUDIO_SAMPLE_RATE
    rtl_tcp_port: int = DEFAULT_RTL_TCP_PORT
    center_freq_hz: int = DEFAULT_GRAVES_VFO_HZ


@dataclass(slots=True)
class GravesDetectorProfile:
    detector_mode: str = "v3"
    detection_min_hz: float = 1_200.0
    detection_max_hz: float = 1_600.0
    trigger_db_above_baseline: float = 11.0
    band_rise_db_min: float = 3.0
    baseline_alpha: float = 0.003
    end_hangover_s: float = 0.20
    min_event_duration_s: float = 0.05
    max_event_duration_s: float = 5.0
    min_gap_between_events_s: float = 0.50
    peak_to_median_db_min: float = 6.5
    near_peak_power_ratio: float = 0.25
    max_near_peak_bins: int = 5
    save_spectrogram: bool = True
    save_wav: bool = True
    save_detection_waterfall: bool = True
    specgram_min_hz: float = 1_200.0
    specgram_max_hz: float = 1_600.0
    specgram_percentile_min: float = 20.0
    specgram_percentile_max: float = 99.8
    event_waterfall_window_seconds: float = 3.0
    event_waterfall_min_hz: float = 1_200.0
    event_waterfall_max_hz: float = 1_600.0
    event_waterfall_percentile_min: float = 20.0
    event_waterfall_percentile_max: float = 99.8
    review_suppress_below_hz: float = 1_000.0
    review_preroll_blocks: int = 2
    v4_min_triggered_frames: int = 2
    v4_min_active_ratio: float = 0.35
    v4_min_longest_run_frames: int = 2
    v4_max_freq_jump_count: int = 2
    v4_min_band_energy_ratio: float = 0.12
    v4_min_onset_db: float = 4.0
    v4_min_score: int = 4
    v4_continuity_max_delta_hz: float = 23.5
    v5_stationary_max_unique_freqs: int = 2
    v5_stationary_max_freq_spread_hz: float = 23.5
    v5_stationary_min_duration_s: float = 0.45
    v5_stationary_min_active_ratio: float = 0.5


@dataclass(slots=True)
class AudioInputConfig:
    device_index: int | None = None
    device_name_contains: str | None = "CABLE Output"
    sample_rate: int = DEFAULT_AUDIO_SAMPLE_RATE
    channels: int = 1
    block_size: int = 4_096
    dtype: str = "float32"
    queue_max_blocks: int = 128


@dataclass(slots=True)
class LocalSdrsharpRuntimeConfig:
    output_dir: str = "meteor_logs"
    log_level: str = "INFO"
    save_spectrogram: bool = True
    save_wav: bool = True
    save_detection_waterfall: bool = True
    waterfall_path: str = "live_waterfall.png"


def load_toml_config(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    with Path(path).open("rb") as handle:
        return tomllib.load(handle)


def load_graves_profile(path: str | Path | None = None) -> GravesProfile:
    data = load_toml_config(path)
    profile = GravesProfile()
    profile_data = data.get("profiles", {}).get("graves", {})
    return merge_dataclass(profile, profile_data)


def load_graves_detector_profile(
    path: str | Path | None = None,
    *,
    profile_name: str = DEFAULT_DETECTION_PROFILE,
) -> GravesDetectorProfile:
    data = load_toml_config(path)
    profile = GravesDetectorProfile()
    profile_data = data.get("detector_profiles", {}).get(profile_name, {})
    return merge_dataclass(profile, profile_data)


def load_audio_input_config(
    path: str | Path | None = None,
    *,
    input_name: str = "sdrsharp_vb_cable",
) -> AudioInputConfig:
    data = load_toml_config(path)
    profile = AudioInputConfig()
    profile_data = data.get("audio_inputs", {}).get(input_name, {})
    return merge_dataclass(profile, profile_data)


def load_local_sdrsharp_runtime_config(
    path: str | Path | None = None,
    *,
    runtime_name: str = "local_sdrsharp",
) -> LocalSdrsharpRuntimeConfig:
    data = load_toml_config(path)
    profile = LocalSdrsharpRuntimeConfig()
    profile_data = data.get("runtime", {}).get(runtime_name, {})
    return merge_dataclass(profile, profile_data)


def merge_dataclass(instance: Any, overrides: dict[str, Any]) -> Any:
    values = asdict(instance)
    valid_names = {field.name for field in fields(instance)}
    for key, value in overrides.items():
        if key in valid_names:
            values[key] = value
    return type(instance)(**values)
