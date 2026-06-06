import csv
import shutil
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from meteor_station.detector import DetectorConfig, MeteorDetector
from fixtures import (
    broadband_false_positive_fixture,
    drifting_meteor_fixture,
    impulse_false_positive_fixture,
    meteor_candidate_fixture,
    repeated_impulse_fixture,
    weak_noise_spike_fixture,
)


def iter_blocks(signal: np.ndarray, block_size: int) -> list[np.ndarray]:
    padded = np.pad(signal.astype(np.float32), (0, (-signal.size) % block_size))
    return [padded[i : i + block_size] for i in range(0, padded.size, block_size)]

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
            with (tmp_dir / "events_v3.csv").open(encoding="utf-8") as handle:
                csv_rows = list(csv.reader(handle))
            return events, csv_rows
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_short_tone_becomes_meteor_candidate(self):
        signal = meteor_candidate_fixture(self.sample_rate)
        events, rows = self._run_detector(signal)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "meteor_candidate")
        self.assertEqual(len(rows), 2)

    def test_long_steady_tone_is_rejected(self):
        noise = 0.001 * np.random.default_rng(2).standard_normal(self.sample_rate).astype(np.float32)
        signal = np.concatenate(
            [
                noise,
                0.22 * np.sin(
                    2.0 * np.pi * 1500.0 * np.arange(int(self.sample_rate * 1.8), dtype=np.float32) / self.sample_rate
                ).astype(np.float32),
            ]
        )
        events, _ = self._run_detector(signal)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "steady_tone_rejected")

    def test_broadband_event_is_rejected(self):
        signal = broadband_false_positive_fixture(self.sample_rate)
        events, _ = self._run_detector(signal)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "broadband_rejected")

    def test_default_detector_config_matches_graves_profile_expectations(self):
        config = DetectorConfig()
        self.assertEqual(config.detector_mode, "v3")
        self.assertEqual(config.detection_min_hz, 1200.0)
        self.assertEqual(config.detection_max_hz, 1600.0)
        self.assertEqual(config.trigger_db_above_baseline, 11.0)
        self.assertEqual(config.peak_to_median_db_min, 6.5)
        self.assertEqual(config.max_near_peak_bins, 5)
        self.assertTrue(config.save_wav)

    def test_v4_impulse_is_rejected(self):
        signal = impulse_false_positive_fixture(self.sample_rate)
        events, rows = self._run_detector(
            signal,
            detector_mode="v4",
            trigger_db_above_baseline=6.0,
            band_rise_db_min=1.0,
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "impulse_rejected")
        self.assertEqual(rows[1][23], "v4")

    def test_v4_drifting_meteor_is_candidate(self):
        signal = drifting_meteor_fixture(self.sample_rate)
        events, rows = self._run_detector(signal, detector_mode="v4")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "meteor_candidate")
        self.assertGreaterEqual(events[0].longest_run_frames, 2)
        self.assertGreaterEqual(float(rows[1][17]), 0.2)

    def test_v4_repeated_impulses_do_not_pass(self):
        signal = repeated_impulse_fixture(self.sample_rate)
        events, _ = self._run_detector(
            signal,
            detector_mode="v4",
            trigger_db_above_baseline=6.0,
            band_rise_db_min=1.0,
        )
        self.assertTrue(events)
        self.assertTrue(all(event.event_type != "meteor_candidate" for event in events))

    def test_v4_weak_spike_is_rejected(self):
        signal = weak_noise_spike_fixture(self.sample_rate)
        events, _ = self._run_detector(
            signal,
            detector_mode="v4",
            trigger_db_above_baseline=6.0,
            band_rise_db_min=1.0,
        )
        self.assertTrue(events)
        self.assertNotEqual(events[0].event_type, "meteor_candidate")


if __name__ == "__main__":
    unittest.main()
