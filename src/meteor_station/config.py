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


@dataclass(slots=True)
class GravesProfile:
    carrier_hz: int = DEFAULT_GRAVES_CARRIER_HZ
    vfo_hz: int = DEFAULT_GRAVES_VFO_HZ
    usb_bandwidth_hz: int = DEFAULT_GRAVES_USB_BANDWIDTH_HZ
    iq_sample_rate: int = DEFAULT_IQ_SAMPLE_RATE
    audio_sample_rate: int = DEFAULT_AUDIO_SAMPLE_RATE
    rtl_tcp_port: int = DEFAULT_RTL_TCP_PORT
    center_freq_hz: int = DEFAULT_GRAVES_VFO_HZ


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


def merge_dataclass(instance: Any, overrides: dict[str, Any]) -> Any:
    values = asdict(instance)
    valid_names = {field.name for field in fields(instance)}
    for key, value in overrides.items():
        if key in valid_names:
            values[key] = value
    return type(instance)(**values)
