import csv
import shutil
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from meteor_station.detector import DetectorConfig, MeteorDetector


def iter_blocks(signal: np.ndarray, block_size: int) -> list[np.ndarray]:
    padded = np.pad(signal.astype(np.float32), (0, (-signal.size) % block_size))
    return [padded[i : i + block_size] for i in range(0, padded.size, block_size)]


def tone(sample_rate: int, duration_s: float, freq_hz: float, amplitude: float) -> np.ndarray:
    t = np.arange(int(sample_rate * duration_s), dtype=np.float32) / sample_rate
    return amplitude * np.sin(2.0 * np.pi * freq_hz * t).astype(np.float32)


class DetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sample_rate = 48_000
        self.block_size = 4_096

    def _run_detector(self, signal: np.ndarray, **config_overrides):
        tmp_dir = Path.cwd() / "test_output_detector"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            detector = MeteorDetector(
                DetectorConfig(
                    sample_rate=self.sample_rate,
                    block_size=self.block_size,
                    output_dir=str(tmp_dir),
                    save_spectrogram=False,
                    save_wav=False,
                    **config_overrides,
                ),
                print_fn=lambda _: None,
            )
            events = []
            timestamp = 0.0
            for block in iter_blocks(signal, self.block_size):
                timestamp += block.size / self.sample_rate
                events.extend(detector.process_block(block, timestamp=timestamp))
            events.extend(detector.finalize_pending(timestamp=timestamp + 0.2))
            csv_rows = list(csv.reader(open(tmp_dir / "events_v3.csv", encoding="utf-8")))
            return events, csv_rows
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_short_tone_becomes_meteor_candidate(self):
        noise = 0.002 * np.random.default_rng(1).standard_normal(self.sample_rate).astype(np.float32)
        signal = np.concatenate([noise, tone(self.sample_rate, 0.35, 1500.0, 0.25)])
        events, rows = self._run_detector(signal)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "meteor_candidate")
        self.assertEqual(len(rows), 2)

    def test_long_steady_tone_is_rejected(self):
        noise = 0.001 * np.random.default_rng(2).standard_normal(self.sample_rate).astype(np.float32)
        signal = np.concatenate([noise, tone(self.sample_rate, 1.8, 1500.0, 0.22)])
        events, _ = self._run_detector(signal)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "steady_tone_rejected")

    def test_broadband_event_is_rejected(self):
        rng = np.random.default_rng(3)
        noise = 0.001 * rng.standard_normal(self.sample_rate).astype(np.float32)
        trigger = tone(self.sample_rate, 0.1, 1500.0, 0.22)
        broadband = 0.25 * rng.standard_normal(int(self.sample_rate * 0.25)).astype(np.float32)
        signal = np.concatenate([noise, trigger, broadband, noise[: self.sample_rate // 2]])
        events, _ = self._run_detector(signal)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "broadband_rejected")


if __name__ == "__main__":
    unittest.main()
