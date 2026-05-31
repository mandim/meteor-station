from __future__ import annotations

import numpy as np


def tone(sample_rate: int, duration_s: float, freq_hz: float, amplitude: float) -> np.ndarray:
    t = np.arange(int(sample_rate * duration_s), dtype=np.float32) / sample_rate
    return amplitude * np.sin(2.0 * np.pi * freq_hz * t).astype(np.float32)


def meteor_candidate_fixture(sample_rate: int) -> np.ndarray:
    rng = np.random.default_rng(101)
    block_aligned_samples = 12 * 4096
    noise = 0.0015 * rng.standard_normal(block_aligned_samples).astype(np.float32)
    burst = tone(sample_rate, 0.35, 1500.0, 0.25)
    tail = tone(sample_rate, 0.08, 1500.0, 0.03)
    quiet = np.zeros(sample_rate // 3, dtype=np.float32)
    return np.concatenate([noise, burst, tail, quiet])


def broadband_false_positive_fixture(sample_rate: int) -> np.ndarray:
    rng = np.random.default_rng(202)
    noise = 0.001 * rng.standard_normal(sample_rate).astype(np.float32)
    duration_s = 0.25
    t = np.arange(int(sample_rate * duration_s), dtype=np.float32) / sample_rate
    broadband = np.zeros_like(t)
    for freq_hz in (1289.0625, 1361.328125, 1433.59375, 1505.859375, 1578.125):
        broadband += 0.06 * np.sin(2.0 * np.pi * freq_hz * t).astype(np.float32)
    broadband += 0.03 * rng.standard_normal(t.size).astype(np.float32)
    return np.concatenate([noise, broadband, noise[: sample_rate // 2]])
