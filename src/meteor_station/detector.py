from __future__ import annotations

import csv
import time
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
from scipy.signal import get_window

from .artifacts import normalize_output_path, save_figure_png
from .config import GravesDetectorProfile


def local_iso_from_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat()


def power_to_db(power_value: float) -> float:
    return 10.0 * np.log10(max(power_value, 1e-12))


@dataclass(slots=True)
class DetectorConfig:
    sample_rate: int = 48_000
    block_size: int = 4_096
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
    steady_tone_min_duration_s: float = 1.50
    steady_tone_max_spread_hz: float = 30.0
    output_dir: str = "meteor_logs"
    csv_filename: str = "events_v3.csv"
    save_spectrogram: bool = True
    save_wav: bool = True
    save_detection_waterfall: bool = True
    detection_waterfall_dir: str = "waterfalls"
    detection_waterfall_prefix: str = "event_v3_"
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

    @classmethod
    def from_graves_profile(
        cls,
        profile: GravesDetectorProfile,
        *,
        sample_rate: int = 48_000,
        block_size: int = 4_096,
        output_dir: str = "meteor_logs",
        detection_waterfall_dir: str = "waterfalls",
        detection_waterfall_prefix: str = "event_v3_",
    ) -> "DetectorConfig":
        return cls(
            sample_rate=sample_rate,
            block_size=block_size,
            detection_min_hz=profile.detection_min_hz,
            detection_max_hz=profile.detection_max_hz,
            trigger_db_above_baseline=profile.trigger_db_above_baseline,
            band_rise_db_min=profile.band_rise_db_min,
            baseline_alpha=profile.baseline_alpha,
            end_hangover_s=profile.end_hangover_s,
            min_event_duration_s=profile.min_event_duration_s,
            max_event_duration_s=profile.max_event_duration_s,
            min_gap_between_events_s=profile.min_gap_between_events_s,
            peak_to_median_db_min=profile.peak_to_median_db_min,
            near_peak_power_ratio=profile.near_peak_power_ratio,
            max_near_peak_bins=profile.max_near_peak_bins,
            output_dir=output_dir,
            save_spectrogram=profile.save_spectrogram,
            save_wav=profile.save_wav,
            save_detection_waterfall=profile.save_detection_waterfall,
            detection_waterfall_dir=detection_waterfall_dir,
            detection_waterfall_prefix=detection_waterfall_prefix,
            specgram_min_hz=profile.specgram_min_hz,
            specgram_max_hz=profile.specgram_max_hz,
            specgram_percentile_min=profile.specgram_percentile_min,
            specgram_percentile_max=profile.specgram_percentile_max,
            event_waterfall_window_seconds=profile.event_waterfall_window_seconds,
            event_waterfall_min_hz=profile.event_waterfall_min_hz,
            event_waterfall_max_hz=profile.event_waterfall_max_hz,
            event_waterfall_percentile_min=profile.event_waterfall_percentile_min,
            event_waterfall_percentile_max=profile.event_waterfall_percentile_max,
            review_suppress_below_hz=profile.review_suppress_below_hz,
        )


@dataclass(slots=True)
class MeteorEvent:
    event_id: int
    start_local: str
    end_local: str
    duration_s: float
    peak_db: float
    avg_db: float
    dominant_freq_hz: float
    freq_spread_hz: float
    baseline_db: float | None
    band_db_at_start: float
    peak_prominence_db: float
    max_near_peak_bins: int
    event_type: str
    image_file: str
    waterfall_file: str
    wav_file: str


class MeteorDetector:
    def __init__(
        self,
        config: DetectorConfig | None = None,
        *,
        time_provider: Callable[[], float] | None = None,
        print_fn: Callable[[str], None] = print,
        detection_waterfall_saver: Callable[[Path, DetectorConfig], str | None] | None = None,
    ) -> None:
        self.config = config or DetectorConfig()
        self.time_provider = time_provider or time.time
        self.print_fn = print_fn
        self.detection_waterfall_saver = detection_waterfall_saver
        self.output_dir = Path(self.config.output_dir)
        self.csv_file = self.output_dir / self.config.csv_filename
        self.window = get_window("hann", self.config.block_size)
        self.freqs = np.fft.rfftfreq(self.config.block_size, d=1.0 / self.config.sample_rate)
        self.band_mask = (
            (self.freqs >= self.config.detection_min_hz)
            & (self.freqs <= self.config.detection_max_hz)
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_csv_header()
        self.reset()

    def reset(self) -> None:
        self.baseline_db: float | None = None
        self.in_event = False
        self.event_id = 0
        self.event_start_ts: float | None = None
        self.event_last_trigger_ts: float | None = None
        self.last_event_end_ts = 0.0
        self.event_frames: list[np.ndarray] = []
        self.event_peak_db_values: list[float] = []
        self.event_peak_freqs: list[float] = []
        self.event_peak_prom_values: list[float] = []
        self.event_near_peak_bins_values: list[int] = []
        self.event_band_db_values: list[float] = []
        self.event_baseline_at_start: float | None = None

    def _ensure_csv_header(self) -> None:
        if self.csv_file.exists():
            return
        with self.csv_file.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "event_id",
                    "start_local",
                    "end_local",
                    "duration_s",
                    "peak_db",
                    "avg_db",
                    "dominant_freq_hz",
                    "freq_spread_hz",
                    "baseline_db",
                    "band_db_at_start",
                    "peak_prominence_db",
                    "max_near_peak_bins",
                    "event_type",
                    "image_file",
                    "waterfall_file",
                    "wav_file",
                ]
            )

    def classify_event(self, duration_s: float, freq_spread_hz: float, max_near_peak_bins: int) -> str:
        if duration_s > self.config.max_event_duration_s:
            return "too_long"
        if (
            duration_s >= self.config.steady_tone_min_duration_s
            and freq_spread_hz <= self.config.steady_tone_max_spread_hz
        ):
            return "steady_tone_rejected"
        if max_near_peak_bins > self.config.max_near_peak_bins:
            return "broadband_rejected"
        return "meteor_candidate"

    def process_block(self, block: np.ndarray, timestamp: float | None = None) -> list[MeteorEvent]:
        x = np.asarray(block, dtype=np.float32)
        if x.ndim != 1:
            raise ValueError("Audio block must be 1-D mono samples.")
        if x.shape[0] != self.config.block_size:
            raise ValueError(
                f"Expected block of {self.config.block_size} samples, got {x.shape[0]}."
            )

        xw = x * self.window
        spectrum = np.fft.rfft(xw)
        power = np.abs(spectrum) ** 2
        band_power_values = power[self.band_mask]
        band_freqs = self.freqs[self.band_mask]

        mean_band_power = float(np.mean(band_power_values))
        median_band_power = float(np.median(band_power_values))
        band_db = power_to_db(mean_band_power)
        median_band_db = power_to_db(median_band_power)

        peak_idx = int(np.argmax(band_power_values))
        peak_freq_hz = float(band_freqs[peak_idx])
        peak_bin_power = float(band_power_values[peak_idx])
        peak_bin_db = power_to_db(peak_bin_power)
        peak_prominence_db = peak_bin_db - median_band_db
        near_peak_bins = int(
            np.sum(band_power_values >= (peak_bin_power * self.config.near_peak_power_ratio))
        )

        now_ts = timestamp if timestamp is not None else self.time_provider()
        events: list[MeteorEvent] = []

        if self.baseline_db is None:
            self.baseline_db = band_db
        if not self.in_event:
            self.baseline_db = (
                (1.0 - self.config.baseline_alpha) * self.baseline_db
                + self.config.baseline_alpha * band_db
            )

        threshold_db = self.baseline_db + self.config.trigger_db_above_baseline
        band_rise_db = band_db - self.baseline_db
        triggered_core = (
            peak_bin_db >= threshold_db
            and peak_prominence_db >= self.config.peak_to_median_db_min
            and band_rise_db >= self.config.band_rise_db_min
        )
        triggered = triggered_core and near_peak_bins <= self.config.max_near_peak_bins

        if triggered_core:
            if not self.in_event and (now_ts - self.last_event_end_ts) >= self.config.min_gap_between_events_s:
                self._start_event(
                    now_ts,
                    peak_bin_db,
                    threshold_db,
                    band_rise_db,
                    peak_prominence_db,
                    peak_freq_hz,
                    near_peak_bins,
                )
            elif self.in_event:
                self.event_last_trigger_ts = now_ts

        if self.in_event:
            self.event_frames.append(x.copy())
            if triggered_core:
                # Classify quality from blocks that actually met the meteor trigger.
                # Hangover frames are kept in the saved review audio/image, but they
                # should not turn a narrowband trigger into a broadband rejection.
                self.event_peak_db_values.append(peak_bin_db)
                self.event_peak_freqs.append(peak_freq_hz)
                self.event_peak_prom_values.append(peak_prominence_db)
                self.event_near_peak_bins_values.append(near_peak_bins)
                self.event_band_db_values.append(band_db)

            if self.event_start_ts is not None and (now_ts - self.event_start_ts) >= self.config.max_event_duration_s:
                event = self._finalize_event(now_ts, forced_type="too_long")
                if event is not None:
                    events.append(event)
            elif self.event_last_trigger_ts is not None and (
                now_ts - self.event_last_trigger_ts
            ) > self.config.end_hangover_s:
                duration_s = now_ts - (self.event_start_ts or now_ts)
                if duration_s >= self.config.min_event_duration_s:
                    event = self._finalize_event(now_ts)
                    if event is not None:
                        events.append(event)
                else:
                    self.print_fn(f"[{local_iso_from_ts(now_ts)}] Short trigger ignored")
                    self._reset_active_event(now_ts)

        return events

    def finalize_pending(self, timestamp: float | None = None) -> list[MeteorEvent]:
        if not self.in_event:
            return []
        now_ts = timestamp if timestamp is not None else self.time_provider()
        if self.event_start_ts is None:
            self._reset_active_event(now_ts)
            return []
        duration_s = now_ts - self.event_start_ts
        if duration_s >= self.config.min_event_duration_s:
            event = self._finalize_event(now_ts)
            return [event] if event is not None else []
        self._reset_active_event(now_ts)
        return []

    def _start_event(
        self,
        now_ts: float,
        peak_bin_db: float,
        threshold_db: float,
        band_rise_db: float,
        peak_prominence_db: float,
        peak_freq_hz: float,
        near_peak_bins: int,
    ) -> None:
        self.in_event = True
        self.event_id += 1
        self.event_start_ts = now_ts
        self.event_last_trigger_ts = now_ts
        self.event_frames = []
        self.event_peak_db_values = []
        self.event_peak_freqs = []
        self.event_peak_prom_values = []
        self.event_near_peak_bins_values = []
        self.event_band_db_values = []
        self.event_baseline_at_start = self.baseline_db
        self.print_fn(
            f"[{local_iso_from_ts(now_ts)}] Event {self.event_id} started | "
            f"peak={peak_bin_db:.2f} dB threshold={threshold_db:.2f} dB "
            f"band_rise={band_rise_db:.2f} dB prom={peak_prominence_db:.2f} dB "
            f"freq={peak_freq_hz:.1f} Hz near_bins={near_peak_bins}"
        )

    def _finalize_event(self, event_end_ts: float, forced_type: str | None = None) -> MeteorEvent | None:
        if not self.event_frames or not self.event_peak_db_values or not self.event_peak_freqs:
            self._reset_active_event(event_end_ts)
            return None

        event_start_ts = self.event_start_ts or event_end_ts
        duration_s = event_end_ts - event_start_ts
        peak_db = float(np.max(self.event_peak_db_values))
        avg_db = float(np.mean(self.event_peak_db_values))
        dom_freq = float(np.median(self.event_peak_freqs))
        freq_spread = float(np.max(self.event_peak_freqs) - np.min(self.event_peak_freqs))
        peak_prominence_db = float(np.max(self.event_peak_prom_values))
        max_near_peak_bins = int(np.max(self.event_near_peak_bins_values))
        band_db_at_start = float(self.event_band_db_values[0])
        event_type = forced_type or self.classify_event(duration_s, freq_spread, max_near_peak_bins)

        image_file = ""
        waterfall_file = ""
        wav_file = ""
        if self.config.save_spectrogram and event_type == "meteor_candidate":
            image_file = str(self.output_dir / f"event_v3_{self.event_id:05d}.png")
            save_spectrogram(
                self.event_frames,
                self.config.sample_rate,
                Path(image_file),
                self.config.specgram_min_hz,
                self.config.specgram_max_hz,
                self.config.specgram_percentile_min,
                self.config.specgram_percentile_max,
                self.config.review_suppress_below_hz,
            )
        if self.config.save_detection_waterfall and event_type == "meteor_candidate":
            waterfall_path = (
                self.output_dir
                / self.config.detection_waterfall_dir
                / f"{self.config.detection_waterfall_prefix}{self.event_id:05d}.png"
            )
            if self.detection_waterfall_saver is not None:
                saved_waterfall = self.detection_waterfall_saver(waterfall_path, self.config)
                if saved_waterfall:
                    waterfall_file = saved_waterfall
        if self.config.save_wav and event_type == "meteor_candidate":
            wav_file = str(self.output_dir / f"event_v3_{self.event_id:05d}.wav")
            save_wav(self.event_frames, self.config.sample_rate, Path(wav_file))

        event = MeteorEvent(
            event_id=self.event_id,
            start_local=local_iso_from_ts(event_start_ts),
            end_local=local_iso_from_ts(event_end_ts),
            duration_s=round(duration_s, 3),
            peak_db=round(peak_db, 2),
            avg_db=round(avg_db, 2),
            dominant_freq_hz=round(dom_freq, 1),
            freq_spread_hz=round(freq_spread, 1),
            baseline_db=round(self.event_baseline_at_start, 2) if self.event_baseline_at_start is not None else None,
            band_db_at_start=round(band_db_at_start, 2),
            peak_prominence_db=round(peak_prominence_db, 2),
            max_near_peak_bins=max_near_peak_bins,
            event_type=event_type,
            image_file=image_file,
            waterfall_file=waterfall_file,
            wav_file=wav_file,
        )
        self._write_event(event)
        self.print_fn(
            f"[{event.end_local}] Event {event.event_id} | "
            f"type={event.event_type} duration={event.duration_s:.2f}s "
            f"peak={event.peak_db:.2f} dB dom_freq={event.dominant_freq_hz:.1f} Hz "
            f"spread={event.freq_spread_hz:.1f} Hz prom={event.peak_prominence_db:.1f} dB "
            f"near_bins={event.max_near_peak_bins}"
        )
        self._reset_active_event(event_end_ts)
        return event

    def _reset_active_event(self, event_end_ts: float) -> None:
        self.in_event = False
        self.last_event_end_ts = event_end_ts
        self.event_start_ts = None
        self.event_last_trigger_ts = None
        self.event_frames = []
        self.event_peak_db_values = []
        self.event_peak_freqs = []
        self.event_peak_prom_values = []
        self.event_near_peak_bins_values = []
        self.event_band_db_values = []
        self.event_baseline_at_start = None

    def _write_event(self, event: MeteorEvent) -> None:
        with self.csv_file.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    event.event_id,
                    event.start_local,
                    event.end_local,
                    event.duration_s,
                    event.peak_db,
                    event.avg_db,
                    event.dominant_freq_hz,
                    event.freq_spread_hz,
                    event.baseline_db if event.baseline_db is not None else "",
                    event.band_db_at_start,
                    event.peak_prominence_db,
                    event.max_near_peak_bins,
                    event.event_type,
                    event.image_file,
                    event.waterfall_file,
                    event.wav_file,
                ]
            )


def save_spectrogram(
    frames: list[np.ndarray],
    sample_rate: int,
    out_path: Path,
    min_hz: float,
    max_hz: float,
    percentile_min: float,
    percentile_max: float,
    suppress_below_hz: float,
) -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    destination = normalize_output_path(out_path)
    x = np.concatenate(frames)
    spectrum_min_hz = max(0.0, min_hz)
    fig = Figure(figsize=(10, 4))
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    with np.errstate(divide="ignore"):
        power, freqs, bins, image = ax.specgram(x, NFFT=1024, Fs=sample_rate, noverlap=768)
    scaled_power = _prepare_review_power_db(
        power,
        freqs,
        min_hz=spectrum_min_hz,
        max_hz=max_hz,
        suppress_below_hz=suppress_below_hz,
    )
    vmin, vmax = _percentile_limits(scaled_power, percentile_min, percentile_max)
    image.set_clim(vmin=vmin, vmax=vmax)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Frequency (Hz)")
    ax.set_title("Meteor Event Spectrogram")
    ax.set_ylim(spectrum_min_hz, max_hz)
    fig.tight_layout()
    save_figure_png(fig, destination, dpi=120)


def save_wav(frames: list[np.ndarray], sample_rate: int, out_path: Path) -> None:
    x = np.concatenate(frames)
    x = np.clip(x, -1.0, 1.0)
    pcm16 = (x * 32767.0).astype(np.int16)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())


def _prepare_review_power_db(
    power: np.ndarray,
    freqs: np.ndarray,
    *,
    min_hz: float,
    max_hz: float,
    suppress_below_hz: float,
) -> np.ndarray:
    power_db = 10.0 * np.log10(np.maximum(power, 1e-12))
    review_power = power_db.copy()
    suppress_limit_hz = max(0.0, suppress_below_hz)
    if suppress_limit_hz > 0:
        review_power[freqs < suppress_limit_hz, :] = np.nan
    band_mask = (freqs >= min_hz) & (freqs <= max_hz)
    if np.any(band_mask):
        return review_power[band_mask, :]
    return review_power


def _percentile_limits(power_db: np.ndarray, percentile_min: float, percentile_max: float) -> tuple[float, float]:
    finite_values = power_db[np.isfinite(power_db)]
    if finite_values.size == 0:
        return (-120.0, 0.0)
    lower = float(np.percentile(finite_values, percentile_min))
    upper = float(np.percentile(finite_values, percentile_max))
    if upper <= lower:
        upper = lower + 1.0
    return lower, upper
