from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from scipy.signal import spectrogram


def is_interactive_matplotlib_backend(backend: str) -> bool:
    normalized = backend.strip().lower()
    if not normalized:
        return False
    if normalized == "agg":
        return False
    if normalized.startswith("module://matplotlib_inline"):
        return False
    return any(
        token in normalized
        for token in (
            "tkagg",
            "qtagg",
            "qt5agg",
            "wxagg",
            "gtk",
            "macosx",
        )
    )


@dataclass(slots=True)
class WaterfallConfig:
    output_path: str
    sample_rate: int
    window_seconds: float = 30.0
    update_interval_s: float = 5.0
    min_hz: float = 0.0
    max_hz: float = 4_000.0
    nfft: int = 1024
    noverlap: int = 768


class _BaseWaterfall:
    def __init__(self, config: WaterfallConfig) -> None:
        self.config = config
        self.max_samples = max(int(config.window_seconds * config.sample_rate), config.nfft)
        self.audio_buffer = np.empty(0, dtype=np.float32)
        self.buffer_start_ts: float | None = None
        self.latest_ts: float | None = None
        self._last_rendered_ts: float | None = None
        self._lock = threading.Lock()

    def consume_block(self, block: np.ndarray, *, start_timestamp: float, sample_rate: int) -> None:
        if sample_rate != self.config.sample_rate:
            raise ValueError(
                f"RollingWaterfall sample rate mismatch: {sample_rate} != {self.config.sample_rate}"
            )
        x = np.asarray(block, dtype=np.float32)
        if x.ndim != 1:
            raise ValueError("RollingWaterfall expects mono audio blocks.")

        with self._lock:
            if self.audio_buffer.size == 0:
                self.buffer_start_ts = start_timestamp
                self.audio_buffer = x.copy()
            else:
                self.audio_buffer = np.concatenate([self.audio_buffer, x])

            overflow = self.audio_buffer.size - self.max_samples
            if overflow > 0:
                self.audio_buffer = self.audio_buffer[overflow:]
                if self.buffer_start_ts is not None:
                    self.buffer_start_ts += overflow / self.config.sample_rate

            self.latest_ts = start_timestamp + (x.size / self.config.sample_rate)

        if self._should_render():
            self.render()

    def _should_render(self) -> bool:
        if self.latest_ts is None:
            return False
        if self.audio_buffer.size < self.config.nfft:
            return False
        if self._last_rendered_ts is None:
            return True
        return (self.latest_ts - self._last_rendered_ts) >= self.config.update_interval_s

    def _compute_waterfall(self) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        with self._lock:
            if self.buffer_start_ts is None or self.latest_ts is None or self.audio_buffer.size < self.config.nfft:
                return None
            buffer_start_ts = self.buffer_start_ts
            audio_buffer = self.audio_buffer.copy()
            latest_ts = self.latest_ts
        freqs, bins, power = spectrogram(
            audio_buffer,
            fs=self.config.sample_rate,
            window="hann",
            nperseg=self.config.nfft,
            noverlap=self.config.noverlap,
            mode="psd",
            scaling="density",
        )
        power_db = 10.0 * np.log10(np.maximum(power, 1e-12))
        return freqs, bins, power_db, buffer_start_ts, latest_ts

    def _tick_positions_and_labels(self, bins: np.ndarray, buffer_start_ts: float | None) -> tuple[np.ndarray, list[str]]:
        if bins.size == 0 or buffer_start_ts is None:
            return np.array([]), []
        tick_count = min(6, bins.size)
        tick_positions = np.linspace(float(bins[0]), float(bins[-1]), num=tick_count)
        tick_labels = [
            datetime.fromtimestamp(buffer_start_ts + tick, UTC).strftime("%H:%M:%S")
            for tick in tick_positions
        ]
        return tick_positions, tick_labels

    def flush(self) -> None:
        if self.audio_buffer.size >= self.config.nfft:
            self.render()

    def close(self) -> None:
        self.flush()

    def render(self) -> None:
        raise NotImplementedError


class RollingWaterfall(_BaseWaterfall):
    def __init__(self, config: WaterfallConfig) -> None:
        super().__init__(config)
        self.output_path = Path(config.output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def render(self) -> None:
        rendered = self._compute_waterfall()
        if rendered is None:
            return
        freqs, bins, power_db, buffer_start_ts, latest_ts = rendered

        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        fig = Figure(figsize=(12, 5))
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        extent = [float(bins[0]), float(bins[-1]), float(freqs[0]), float(freqs[-1])]
        ax.imshow(power_db, origin="lower", aspect="auto", extent=extent, cmap="viridis")
        ax.set_ylabel("Frequency (Hz)")
        ax.set_xlabel("UTC time")
        ax.set_title("Live GRAVES Audio Waterfall")
        ax.set_ylim(self.config.min_hz, self.config.max_hz)

        tick_positions, tick_labels = self._tick_positions_and_labels(bins, buffer_start_ts)
        if tick_labels:
            ax.set_xticks(tick_positions, tick_labels)

        fig.tight_layout()
        fig.savefig(self.output_path, dpi=120)
        self._last_rendered_ts = latest_ts


class LiveWaterfallWindow(_BaseWaterfall):
    def __init__(self, config: WaterfallConfig) -> None:
        super().__init__(config)
        import matplotlib.pyplot as plt

        plt.ion()
        self.plt = plt
        self.fig, self.ax = plt.subplots(figsize=(12, 5))
        self._is_interactive_backend = is_interactive_matplotlib_backend(plt.get_backend())
        self.image = None
        self.ax.set_ylabel("Frequency (Hz)")
        self.ax.set_xlabel("UTC time")
        self.ax.set_title("Live GRAVES Audio Waterfall")
        self.ax.set_ylim(self.config.min_hz, self.config.max_hz)
        self.fig.tight_layout()
        if self._is_interactive_backend:
            self.fig.show()

    def consume_block(self, block: np.ndarray, *, start_timestamp: float, sample_rate: int) -> None:
        if sample_rate != self.config.sample_rate:
            raise ValueError(
                f"RollingWaterfall sample rate mismatch: {sample_rate} != {self.config.sample_rate}"
            )
        x = np.asarray(block, dtype=np.float32)
        if x.ndim != 1:
            raise ValueError("RollingWaterfall expects mono audio blocks.")

        with self._lock:
            if self.audio_buffer.size == 0:
                self.buffer_start_ts = start_timestamp
                self.audio_buffer = x.copy()
            else:
                self.audio_buffer = np.concatenate([self.audio_buffer, x])

            overflow = self.audio_buffer.size - self.max_samples
            if overflow > 0:
                self.audio_buffer = self.audio_buffer[overflow:]
                if self.buffer_start_ts is not None:
                    self.buffer_start_ts += overflow / self.config.sample_rate

            self.latest_ts = start_timestamp + (x.size / self.config.sample_rate)

    def render(self) -> None:
        rendered = self._compute_waterfall()
        if rendered is None:
            return
        freqs, bins, power_db, buffer_start_ts, latest_ts = rendered
        extent = [float(bins[0]), float(bins[-1]), float(freqs[0]), float(freqs[-1])]

        if self.image is None:
            self.image = self.ax.imshow(
                power_db,
                origin="lower",
                aspect="auto",
                extent=extent,
                cmap="viridis",
            )
        else:
            self.image.set_data(power_db)
            self.image.set_extent(extent)

        self.ax.set_ylim(self.config.min_hz, self.config.max_hz)
        tick_positions, tick_labels = self._tick_positions_and_labels(bins, buffer_start_ts)
        if tick_labels:
            self.ax.set_xticks(tick_positions, tick_labels)
        self.fig.canvas.draw_idle()
        if self._is_interactive_backend:
            self.fig.canvas.flush_events()
            self.plt.pause(0.001)
        self._last_rendered_ts = latest_ts

    def pump_once(self) -> None:
        if self._should_render():
            self.render()
        elif self._is_interactive_backend:
            self.fig.canvas.flush_events()
            self.plt.pause(0.001)

    def is_open(self) -> bool:
        return self.plt.fignum_exists(self.fig.number)

    def close(self) -> None:
        super().close()
        self.plt.close(self.fig)


class LiveAudioMonitor:
    def __init__(self, sample_rate: int, *, device: int | None = None, blocksize: int = 0) -> None:
        import sounddevice as sd

        self.sample_rate = sample_rate
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=128)
        self._closed = False
        self._lock = threading.Lock()

        def callback(outdata, frames, time_info, status) -> None:  # pragma: no cover - hardware callback
            del time_info
            if status:
                pass

            chunks: list[np.ndarray] = []
            remaining = frames
            while remaining > 0:
                try:
                    chunk = self._queue.get_nowait()
                except queue.Empty:
                    break
                if chunk.size <= remaining:
                    chunks.append(chunk)
                    remaining -= chunk.size
                else:
                    chunks.append(chunk[:remaining])
                    try:
                        self._queue.put_nowait(chunk[remaining:])
                    except queue.Full:
                        pass
                    remaining = 0

            if chunks:
                data = np.concatenate(chunks)
            else:
                data = np.zeros(frames, dtype=np.float32)

            if data.size < frames:
                data = np.pad(data, (0, frames - data.size))

            outdata[:, 0] = data.astype(np.float32, copy=False)

        self.stream = sd.OutputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            device=device,
            blocksize=blocksize,
            callback=callback,
        )
        self.stream.start()

    def consume_block(self, block: np.ndarray, *, start_timestamp: float, sample_rate: int) -> None:
        del start_timestamp
        if sample_rate != self.sample_rate:
            raise ValueError(f"LiveAudioMonitor sample rate mismatch: {sample_rate} != {self.sample_rate}")
        if self._closed:
            return
        x = np.asarray(block, dtype=np.float32)
        with self._lock:
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            self._queue.put_nowait(x.copy())

    def flush(self) -> None:
        return

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.stream.stop()
        self.stream.close()
