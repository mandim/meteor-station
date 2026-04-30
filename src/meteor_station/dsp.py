from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable

import numpy as np
from scipy.signal import firwin, lfilter, lfilter_zi, resample_poly


@dataclass(slots=True)
class UsbDemodulatorConfig:
    input_sample_rate: int
    output_sample_rate: int = 48_000
    usb_bandwidth_hz: float = 3_000.0
    center_freq_hz: float = 143_048_400.0
    vfo_hz: float = 143_048_400.0
    block_size: int = 4_096
    lowpass_taps: int = 129


class UsbDemodulator:
    def __init__(self, config: UsbDemodulatorConfig) -> None:
        self.config = config
        cutoff_hz = min(self.config.usb_bandwidth_hz, self.config.input_sample_rate * 0.45)
        self.filter_taps = firwin(
            self.config.lowpass_taps,
            cutoff_hz,
            fs=self.config.input_sample_rate,
        ).astype(np.float32)
        zi = lfilter_zi(self.filter_taps, [1.0]).astype(np.complex64)
        self.filter_state = zi * 0.0
        self.sample_index = 0
        self.shift_hz = self.config.center_freq_hz - self.config.vfo_hz
        ratio = Fraction(self.config.output_sample_rate, self.config.input_sample_rate).limit_denominator()
        self.resample_up = ratio.numerator
        self.resample_down = ratio.denominator
        self.audio_buffer = np.empty(0, dtype=np.float32)

    def process_iq(self, iq_samples: np.ndarray) -> list[np.ndarray]:
        iq = np.asarray(iq_samples, dtype=np.complex64)
        if iq.ndim != 1:
            raise ValueError("IQ samples must be 1-D complex samples.")
        shifted = iq * self._oscillator(len(iq))
        filtered, self.filter_state = lfilter(
            self.filter_taps,
            [1.0],
            shifted,
            zi=self.filter_state,
        )
        usb_audio = np.real(filtered).astype(np.float32)
        resampled = resample_poly(usb_audio, self.resample_up, self.resample_down).astype(np.float32)
        if self.audio_buffer.size == 0:
            self.audio_buffer = resampled
        else:
            self.audio_buffer = np.concatenate([self.audio_buffer, resampled])

        blocks: list[np.ndarray] = []
        while self.audio_buffer.size >= self.config.block_size:
            blocks.append(self.audio_buffer[: self.config.block_size].copy())
            self.audio_buffer = self.audio_buffer[self.config.block_size :]
        return blocks

    def flush(self) -> list[np.ndarray]:
        self.audio_buffer = np.empty(0, dtype=np.float32)
        return []

    def _oscillator(self, count: int) -> np.ndarray:
        if self.shift_hz == 0:
            self.sample_index += count
            return np.ones(count, dtype=np.complex64)
        n = np.arange(self.sample_index, self.sample_index + count, dtype=np.float64)
        self.sample_index += count
        phase = 2.0 * np.pi * self.shift_hz * n / self.config.input_sample_rate
        return np.exp(1j * phase).astype(np.complex64)


def rtl_tcp_bytes_to_iq(payload: bytes) -> np.ndarray:
    raw = np.frombuffer(payload, dtype=np.uint8)
    if raw.size % 2 != 0:
        raw = raw[:-1]
    iq_u8 = raw.reshape(-1, 2).astype(np.float32)
    i = (iq_u8[:, 0] - 127.5) / 128.0
    q = (iq_u8[:, 1] - 127.5) / 128.0
    return (i + 1j * q).astype(np.complex64)


def chunk_complex_samples(samples: np.ndarray, chunk_size: int) -> Iterable[np.ndarray]:
    for start in range(0, samples.size, chunk_size):
        yield samples[start : start + chunk_size]
