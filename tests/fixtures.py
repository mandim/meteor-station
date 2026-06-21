from __future__ import annotations

import numpy as np


def tone(sample_rate: int, duration_s: float, freq_hz: float, amplitude: float) -> np.ndarray:
    t = np.arange(int(sample_rate * duration_s), dtype=np.float32) / sample_rate
    return amplitude * np.sin(2.0 * np.pi * freq_hz * t).astype(np.float32)


def meteor_candidate_fixture(sample_rate: int) -> np.ndarray:
    rng = np.random.default_rng(101)
    block_aligned_samples = 12 * 4096
    noise = 0.0015 * rng.standard_normal(block_aligned_samples).astype(np.float32)
    duration_s = 0.35
    t = np.arange(int(sample_rate * duration_s), dtype=np.float32) / sample_rate
    start_freq = 1488.0
    stop_freq = 1516.0
    burst = 0.25 * np.sin(
        2.0 * np.pi * (start_freq * t + ((stop_freq - start_freq) / (2.0 * duration_s)) * t * t)
    ).astype(np.float32)
    tail = tone(sample_rate, 0.08, 1510.0, 0.03)
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


def impulse_false_positive_fixture(sample_rate: int) -> np.ndarray:
    rng = np.random.default_rng(303)
    noise = 0.001 * rng.standard_normal(sample_rate).astype(np.float32)
    impulse = np.zeros(4096, dtype=np.float32)
    impulse[512:544] = 0.6 * rng.standard_normal(32).astype(np.float32)
    return np.concatenate([noise[: 4096 * 2], impulse, noise[: sample_rate // 2]])


def repeated_impulse_fixture(sample_rate: int) -> np.ndarray:
    rng = np.random.default_rng(404)
    noise = 0.001 * rng.standard_normal(sample_rate).astype(np.float32)
    duration_s = 0.11
    t = np.arange(int(sample_rate * duration_s), dtype=np.float32) / sample_rate
    pulse = 0.025 * rng.standard_normal(t.size).astype(np.float32)
    for freq_hz in (1260.0, 1350.0, 1440.0, 1530.0, 1580.0):
        pulse += 0.05 * np.sin(2.0 * np.pi * freq_hz * t).astype(np.float32)
    spacer = np.zeros(int(sample_rate * 0.6), dtype=np.float32)
    return np.concatenate([noise[:4096], pulse, spacer, pulse, noise[: sample_rate // 3]])


def weak_noise_spike_fixture(sample_rate: int) -> np.ndarray:
    rng = np.random.default_rng(505)
    noise = 0.0015 * rng.standard_normal(sample_rate).astype(np.float32)
    spike = tone(sample_rate, 0.07, 1500.0, 0.015)
    return np.concatenate([noise[: 4096 * 2], spike, noise[: sample_rate // 2]])


def drifting_meteor_fixture(sample_rate: int) -> np.ndarray:
    rng = np.random.default_rng(606)
    noise = 0.0012 * rng.standard_normal(4096 * 12).astype(np.float32)
    duration_s = 0.45
    t = np.arange(int(sample_rate * duration_s), dtype=np.float32) / sample_rate
    start_freq = 1460.0
    stop_freq = 1520.0
    sweep = 0.18 * np.sin(
        2.0 * np.pi * (start_freq * t + ((stop_freq - start_freq) / (2.0 * duration_s)) * t * t)
    ).astype(np.float32)
    tail = tone(sample_rate, 0.10, 1510.0, 0.03)
    quiet = np.zeros(sample_rate // 4, dtype=np.float32)
    return np.concatenate([noise, sweep, tail, quiet])


def stationary_carrier_false_positive_fixture(sample_rate: int) -> np.ndarray:
    rng = np.random.default_rng(707)
    noise = 0.0012 * rng.standard_normal(4096 * 10).astype(np.float32)
    burst = tone(sample_rate, 0.62, 1546.875, 0.22)
    quiet = np.zeros(sample_rate // 3, dtype=np.float32)
    return np.concatenate([noise, burst, quiet])
