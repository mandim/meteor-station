from __future__ import annotations

import queue
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import numpy as np


@dataclass(slots=True)
class InputDeviceInfo:
    index: int
    name: str
    max_input_channels: int
    default_samplerate: float


def list_input_devices() -> list[InputDeviceInfo]:
    try:
        import sounddevice as sd
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on local environment
        raise RuntimeError(
            "sounddevice is required for live audio device enumeration. Install project dependencies first."
        ) from exc

    devices = sd.query_devices()
    results: list[InputDeviceInfo] = []
    for index, device in enumerate(devices):
        max_input_channels = int(device.get("max_input_channels", 0))
        if max_input_channels <= 0:
            continue
        results.append(
            InputDeviceInfo(
                index=index,
                name=str(device.get("name", f"device-{index}")),
                max_input_channels=max_input_channels,
                default_samplerate=float(device.get("default_samplerate", 0.0)),
            )
        )
    return results


def resolve_input_device(
    *,
    device_index: int | None = None,
    device_name_contains: str | None = None,
    devices: list[InputDeviceInfo] | None = None,
) -> InputDeviceInfo:
    available = list_input_devices() if devices is None else devices
    if device_index is not None:
        for device in available:
            if device.index == device_index:
                return device
        raise ValueError(f"Input device index {device_index} was not found.")

    if device_name_contains:
        needle = device_name_contains.casefold()
        matches = [device for device in available if needle in device.name.casefold()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            device_names = ", ".join(f"{device.index}:{device.name}" for device in matches)
            raise ValueError(
                f"Input device name '{device_name_contains}' matched multiple devices: {device_names}"
            )
        raise ValueError(f"No input device name matched '{device_name_contains}'.")

    raise ValueError("No input device was configured. Set device_index or device_name_contains.")


class AudioBlockAccumulator:
    def __init__(
        self,
        *,
        block_size: int,
        channels: int,
        queue_max_blocks: int,
        status_warning_interval_s: float = 10.0,
        time_provider: Callable[[], float] | None = None,
    ) -> None:
        self.block_size = block_size
        self.channels = channels
        self.queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=queue_max_blocks)
        self.status_warning_interval_s = status_warning_interval_s
        self.time_provider = time_provider or time.time
        self._buffer = np.empty(0, dtype=np.float32)
        self._lock = threading.Lock()
        self._closed = False
        self._pending_status_messages: list[str] = []
        self._last_status_report_ts = 0.0
        self._dropped_blocks = 0

    def append_frames(self, frames: np.ndarray, *, status: object | None = None) -> None:
        audio = np.asarray(frames, dtype=np.float32)
        if audio.ndim == 1:
            mono = audio
        elif audio.ndim == 2:
            if audio.shape[1] != self.channels:
                raise ValueError(
                    f"Expected {self.channels} input channels, got {audio.shape[1]}."
                )
            mono = audio[:, 0] if self.channels == 1 else np.mean(audio, axis=1, dtype=np.float32)
        else:
            raise ValueError("Audio callback frames must be 1-D or 2-D.")

        if status:
            self._record_status(status)

        with self._lock:
            if self._buffer.size == 0:
                self._buffer = mono.copy()
            else:
                self._buffer = np.concatenate([self._buffer, mono])

            while self._buffer.size >= self.block_size:
                block = self._buffer[: self.block_size].copy()
                self._buffer = self._buffer[self.block_size :]
                try:
                    self.queue.put_nowait(block)
                except queue.Full:
                    self._dropped_blocks += 1

    def next_block(self, *, timeout: float = 0.5) -> np.ndarray | None:
        item = self.queue.get(timeout=timeout)
        return item

    def drain_partial_block(self) -> np.ndarray | None:
        with self._lock:
            if self._buffer.size == 0:
                return None
            return self._buffer.copy()

    def close(self) -> None:
        self._closed = True
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass

    def pop_status_messages(self) -> list[str]:
        with self._lock:
            messages = list(self._pending_status_messages)
            self._pending_status_messages.clear()
        if self._dropped_blocks:
            messages.append(f"Audio block queue overflowed; dropped {self._dropped_blocks} block(s).")
            self._dropped_blocks = 0
        return messages

    def _record_status(self, status: object) -> None:
        now_ts = self.time_provider()
        if (now_ts - self._last_status_report_ts) < self.status_warning_interval_s:
            return
        self._last_status_report_ts = now_ts
        with self._lock:
            self._pending_status_messages.append(f"Audio callback status: {status}")


class SoundDeviceAudioSource:
    def __init__(
        self,
        *,
        device: int,
        sample_rate: int,
        channels: int,
        block_size: int,
        dtype: str,
        queue_max_blocks: int,
        status_warning_interval_s: float = 10.0,
    ) -> None:
        try:
            import sounddevice as sd
        except ModuleNotFoundError as exc:  # pragma: no cover - depends on local environment
            raise RuntimeError(
                "sounddevice is required for live SDR# audio capture. Install project dependencies first."
            ) from exc

        self.sample_rate = sample_rate
        self.block_size = block_size
        self.accumulator = AudioBlockAccumulator(
            block_size=block_size,
            channels=channels,
            queue_max_blocks=queue_max_blocks,
            status_warning_interval_s=status_warning_interval_s,
        )

        def callback(indata, frames, time_info, status) -> None:  # pragma: no cover - hardware callback
            del frames, time_info
            self.accumulator.append_frames(indata, status=status)

        self.stream = sd.InputStream(
            device=device,
            channels=channels,
            samplerate=sample_rate,
            dtype=dtype,
            callback=callback,
        )

    def start(self) -> None:
        self.stream.start()

    def iter_blocks(self, *, stop_event: threading.Event | None = None) -> Iterator[np.ndarray]:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            try:
                block = self.accumulator.next_block(timeout=0.5)
            except queue.Empty:
                continue
            if block is None:
                break
            yield block

    def finalize(self) -> list[np.ndarray]:
        tail = self.accumulator.drain_partial_block()
        if tail is None:
            return []
        return [tail]

    def pop_status_messages(self) -> list[str]:
        return self.accumulator.pop_status_messages()

    def close(self) -> None:
        self.accumulator.close()
        self.stream.stop()
        self.stream.close()


def load_wav_mono(path: str | Path, *, expected_sample_rate: int) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        sample_rate = handle.getframerate()
        channel_count = handle.getnchannels()
        sample_width = handle.getsampwidth()
        frame_count = handle.getnframes()
        raw = handle.readframes(frame_count)

    if sample_rate != expected_sample_rate:
        raise ValueError(
            f"WAV sample rate {sample_rate} does not match expected sample rate {expected_sample_rate}."
        )
    if sample_width not in (1, 2, 4):
        raise ValueError(f"Unsupported WAV sample width {sample_width} bytes.")

    if sample_width == 1:
        audio = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    else:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0

    if channel_count > 1:
        audio = audio.reshape(-1, channel_count).mean(axis=1, dtype=np.float32)

    return audio.astype(np.float32, copy=False)
