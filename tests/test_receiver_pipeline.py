import csv
import shutil
import sys
import unittest
import warnings
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from fixtures import broadband_false_positive_fixture, meteor_candidate_fixture
from meteor_station.config import load_graves_detector_profile
from meteor_station.detector import DetectorConfig, MeteorDetector
from meteor_station.dsp import chunk_complex_samples
from meteor_station.monitoring import (
    LiveWaterfallWindow,
    RollingWaterfall,
    WaterfallConfig,
    is_interactive_matplotlib_backend,
)
from meteor_station.receiver import NetworkMeteorReceiver, ReceiverConfig


class ReceiverPipelineTests(unittest.TestCase):
    def test_load_graves_detector_profile_defaults(self):
        profile = load_graves_detector_profile()
        self.assertEqual(profile.detection_min_hz, 1200.0)
        self.assertEqual(profile.detection_max_hz, 1600.0)
        self.assertEqual(profile.max_near_peak_bins, 5)
        self.assertTrue(profile.save_wav)

    def test_interactive_backend_detection(self):
        self.assertTrue(is_interactive_matplotlib_backend("TkAgg"))
        self.assertTrue(is_interactive_matplotlib_backend("QtAgg"))
        self.assertTrue(is_interactive_matplotlib_backend("Qt5Agg"))
        self.assertFalse(is_interactive_matplotlib_backend("Agg"))
        self.assertFalse(is_interactive_matplotlib_backend("module://matplotlib_inline.backend_inline"))

    def test_end_to_end_iq_pipeline_writes_event_outputs(self):
        iq_sample_rate = 240_000
        audio_sample_rate = 48_000
        duration_s = 2.2
        total_samples = int(iq_sample_rate * duration_s)
        t = np.arange(total_samples, dtype=np.float32) / iq_sample_rate
        iq = np.zeros(total_samples, dtype=np.complex64)

        start = int(iq_sample_rate * 1.0)
        stop = int(iq_sample_rate * 1.35)
        iq[start:stop] = np.exp(1j * 2.0 * np.pi * 1_600.0 * t[: stop - start]).astype(np.complex64)
        tail_stop = int(iq_sample_rate * 1.60)
        iq[stop:tail_stop] = 0.05 * np.exp(1j * 2.0 * np.pi * 1_600.0 * t[: tail_stop - stop]).astype(np.complex64)
        iq += 0.001 * (
            np.random.default_rng(4).standard_normal(total_samples)
            + 1j * np.random.default_rng(5).standard_normal(total_samples)
        ).astype(np.complex64)

        tmp_dir = Path.cwd() / "test_output_receiver"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            detector = MeteorDetector(
                DetectorConfig(
                    sample_rate=audio_sample_rate,
                    block_size=4_096,
                    output_dir=str(tmp_dir),
                    save_spectrogram=True,
                    save_wav=True,
                    max_near_peak_bins=5,
                ),
                print_fn=lambda _: None,
            )
            receiver = NetworkMeteorReceiver(
                ReceiverConfig(
                    server_host="127.0.0.1",
                    server_port=1234,
                    iq_sample_rate=iq_sample_rate,
                    audio_sample_rate=audio_sample_rate,
                    center_freq_hz=143_048_400,
                    vfo_hz=143_048_400,
                    usb_bandwidth_hz=3_000,
                ),
                detector,
            )

            timestamp = 0.0
            events = []
            for chunk in chunk_complex_samples(iq, 24_000):
                events.extend(receiver.process_iq_samples(chunk, start_timestamp=timestamp))
                timestamp += chunk.size / iq_sample_rate
            events.extend(receiver.flush(timestamp))

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, "meteor_candidate")

            csv_path = tmp_dir / "events_v3.csv"
            with csv_path.open(encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(len(rows), 2)
            png_path = Path(rows[1][13])
            self.assertTrue(png_path.exists(), "expected spectrogram PNG to be created")
            waterfall_path = Path(rows[1][14])
            self.assertTrue(waterfall_path.exists(), "expected detection waterfall PNG to be created")
            wav_path = Path(rows[1][15])
            self.assertTrue(wav_path.exists(), "expected review WAV to be created")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_rejected_event_does_not_write_detection_waterfall(self):
        audio_sample_rate = 48_000
        block_size = 4_096
        saver_calls: list[Path] = []

        tmp_dir = Path.cwd() / "test_output_receiver_rejected"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            detector = MeteorDetector(
                DetectorConfig(
                    sample_rate=audio_sample_rate,
                    block_size=block_size,
                    output_dir=str(tmp_dir),
                    save_spectrogram=False,
                    save_detection_waterfall=True,
                    max_near_peak_bins=5,
                ),
                print_fn=lambda _: None,
                detection_waterfall_saver=lambda path, config: saver_calls.append(path) or str(path),
            )

            events = []
            timestamp = 0.0
            signal = broadband_false_positive_fixture(audio_sample_rate)

            padded = np.pad(signal, (0, (-signal.size) % block_size))
            for start in range(0, padded.size, block_size):
                block = padded[start : start + block_size]
                timestamp += block.size / audio_sample_rate
                events.extend(detector.process_block(block, timestamp=timestamp))
            events.extend(detector.finalize_pending(timestamp=timestamp + 0.2))

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, "broadband_rejected")
            self.assertEqual(events[0].waterfall_file, "")
            self.assertEqual(saver_calls, [])

            with (tmp_dir / "events_v3.csv").open(encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[1][14], "")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_receiver_can_write_rolling_waterfall_png(self):
        iq_sample_rate = 240_000
        audio_sample_rate = 48_000
        duration_s = 1.4
        total_samples = int(iq_sample_rate * duration_s)
        t = np.arange(total_samples, dtype=np.float32) / iq_sample_rate
        iq = (0.2 * np.exp(1j * 2.0 * np.pi * 1_600.0 * t)).astype(np.complex64)

        tmp_dir = Path.cwd() / "test_output_receiver_waterfall"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            detector = MeteorDetector(
                DetectorConfig(
                    sample_rate=audio_sample_rate,
                    block_size=4_096,
                    output_dir=str(tmp_dir),
                    save_spectrogram=False,
                ),
                print_fn=lambda _: None,
            )
            waterfall = RollingWaterfall(
                WaterfallConfig(
                    output_path=str(tmp_dir / "live_waterfall.png"),
                    sample_rate=audio_sample_rate,
                    window_seconds=5.0,
                    update_interval_s=0.5,
                    min_hz=0.0,
                    max_hz=4_000.0,
                    percentile_min=20.0,
                    percentile_max=99.8,
                    suppress_below_hz=1_000.0,
                )
            )
            receiver = NetworkMeteorReceiver(
                ReceiverConfig(
                    server_host="127.0.0.1",
                    server_port=1234,
                    iq_sample_rate=iq_sample_rate,
                    audio_sample_rate=audio_sample_rate,
                    center_freq_hz=143_048_400,
                    vfo_hz=143_048_400,
                    usb_bandwidth_hz=3_000,
                ),
                detector,
                audio_sinks=[waterfall],
            )

            timestamp = 1_700_000_000.0
            for chunk in chunk_complex_samples(iq, 24_000):
                receiver.process_iq_samples(chunk, start_timestamp=timestamp)
                timestamp += chunk.size / iq_sample_rate
            receiver.flush(timestamp)

            self.assertTrue((tmp_dir / "live_waterfall.png").exists())
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_rolling_waterfall_accepts_windows_style_relative_output_path(self):
        audio_sample_rate = 48_000
        tmp_dir = Path.cwd() / "test_output_receiver_windows_path"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        original_cwd = Path.cwd()
        try:
            import os

            os.chdir(tmp_dir)
            waterfall = RollingWaterfall(
                WaterfallConfig(
                    output_path=r"meteor_logs\live_waterfall.png",
                    sample_rate=audio_sample_rate,
                    window_seconds=5.0,
                    update_interval_s=0.25,
                    min_hz=0.0,
                    max_hz=4_000.0,
                    percentile_min=20.0,
                    percentile_max=99.8,
                    suppress_below_hz=1_000.0,
                )
            )
            sample_count = int(audio_sample_rate * 1.0)
            t = np.arange(sample_count, dtype=np.float32) / audio_sample_rate
            signal = (0.2 * np.sin(2.0 * np.pi * 1_600.0 * t)).astype(np.float32)
            block_size = 4_096
            timestamp = 1_700_000_000.0

            for start in range(0, sample_count - block_size + 1, block_size):
                block = signal[start : start + block_size]
                waterfall.consume_block(block, start_timestamp=timestamp, sample_rate=audio_sample_rate)
                timestamp += block.size / audio_sample_rate
            waterfall.flush()

            self.assertTrue((tmp_dir / "meteor_logs" / "live_waterfall.png").exists())
        finally:
            os.chdir(original_cwd)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_rolling_waterfall_can_save_detection_snapshot_without_overwriting_live_output(self):
        audio_sample_rate = 48_000
        tmp_dir = Path.cwd() / "test_output_receiver_waterfall_snapshot"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            waterfall = RollingWaterfall(
                WaterfallConfig(
                    output_path=str(tmp_dir / "live_waterfall.png"),
                    sample_rate=audio_sample_rate,
                    window_seconds=5.0,
                    update_interval_s=0.5,
                    min_hz=0.0,
                    max_hz=4_000.0,
                    percentile_min=20.0,
                    percentile_max=99.8,
                    suppress_below_hz=1_000.0,
                )
            )
            sample_count = int(audio_sample_rate * 1.4)
            t = np.arange(sample_count, dtype=np.float32) / audio_sample_rate
            signal = (0.2 * np.sin(2.0 * np.pi * 1_600.0 * t)).astype(np.float32)
            block_size = 4_096
            timestamp = 1_700_000_000.0

            for start in range(0, sample_count - block_size + 1, block_size):
                block = signal[start : start + block_size]
                waterfall.consume_block(block, start_timestamp=timestamp, sample_rate=audio_sample_rate)
                timestamp += block.size / audio_sample_rate
            waterfall.flush()

            live_path = tmp_dir / "live_waterfall.png"
            snapshot_path = tmp_dir / "waterfalls" / "event_v3_00001.png"
            saved_path = waterfall.save_snapshot(
                snapshot_path,
                window_seconds=3.0,
                min_hz=1_200.0,
                max_hz=1_600.0,
                percentile_min=20.0,
                percentile_max=99.8,
                suppress_below_hz=1_000.0,
            )

            self.assertEqual(saved_path, str(snapshot_path))
            self.assertTrue(live_path.exists())
            self.assertTrue(snapshot_path.exists())
            self.assertNotEqual(live_path, snapshot_path)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_process_iq_samples_defaults_to_local_wall_clock(self):
        iq_sample_rate = 240_000
        audio_sample_rate = 48_000
        block_size = 4_096
        chunk_size = 24_000
        iq = np.ones(chunk_size, dtype=np.complex64)
        seen_timestamps: list[float] = []

        tmp_dir = Path.cwd() / "test_output_receiver_wall_clock"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            class CaptureSink:
                def consume_block(self, block, *, start_timestamp: float, sample_rate: int) -> None:
                    del block, sample_rate
                    seen_timestamps.append(start_timestamp)

                def flush(self) -> None:
                    return None

                def close(self) -> None:
                    return None

            detector = MeteorDetector(
                DetectorConfig(
                    sample_rate=audio_sample_rate,
                    block_size=block_size,
                    output_dir=str(tmp_dir),
                    save_spectrogram=False,
                ),
                print_fn=lambda _: None,
            )
            receiver = NetworkMeteorReceiver(
                ReceiverConfig(
                    server_host="127.0.0.1",
                    server_port=1234,
                    iq_sample_rate=iq_sample_rate,
                    audio_sample_rate=audio_sample_rate,
                    center_freq_hz=143_048_400,
                    vfo_hz=143_048_400,
                    usb_bandwidth_hz=3_000,
                ),
                detector,
                audio_sinks=[CaptureSink()],
            )

            expected_start = 1_700_000_000.0

            with mock.patch("meteor_station.receiver.time.time", return_value=expected_start):
                receiver.process_iq_samples(iq)

            self.assertTrue(seen_timestamps)
            self.assertEqual(seen_timestamps[0], expected_start)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_live_waterfall_window_renders_without_displaying_ui(self):
        import matplotlib

        matplotlib.use("Agg")

        iq_sample_rate = 240_000
        audio_sample_rate = 48_000
        duration_s = 1.0
        total_samples = int(iq_sample_rate * duration_s)
        t = np.arange(total_samples, dtype=np.float32) / iq_sample_rate
        iq = (0.2 * np.exp(1j * 2.0 * np.pi * 1_600.0 * t)).astype(np.complex64)

        tmp_dir = Path.cwd() / "test_output_receiver_window"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        window = None
        try:
            detector = MeteorDetector(
                DetectorConfig(
                    sample_rate=audio_sample_rate,
                    block_size=4_096,
                    output_dir=str(tmp_dir),
                    save_spectrogram=False,
                ),
                print_fn=lambda _: None,
            )
            window = LiveWaterfallWindow(
                WaterfallConfig(
                    output_path=str(tmp_dir / "unused.png"),
                    sample_rate=audio_sample_rate,
                    window_seconds=5.0,
                    update_interval_s=0.25,
                    min_hz=0.0,
                    max_hz=4_000.0,
                    percentile_min=20.0,
                    percentile_max=99.8,
                )
            )
            receiver = NetworkMeteorReceiver(
                ReceiverConfig(
                    server_host="127.0.0.1",
                    server_port=1234,
                    iq_sample_rate=iq_sample_rate,
                    audio_sample_rate=audio_sample_rate,
                    center_freq_hz=143_048_400,
                    vfo_hz=143_048_400,
                    usb_bandwidth_hz=3_000,
                ),
                detector,
                audio_sinks=[window],
            )

            timestamp = 1_700_000_000.0
            for chunk in chunk_complex_samples(iq, 24_000):
                receiver.process_iq_samples(chunk, start_timestamp=timestamp)
                timestamp += chunk.size / iq_sample_rate
            receiver.flush(timestamp)

            self.assertIsNotNone(window.image)
            self.assertFalse(window._is_interactive_backend)
        finally:
            if window is not None:
                window.close()
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_live_waterfall_window_treats_tkagg_as_interactive(self):
        import matplotlib
        import matplotlib.pyplot as plt

        matplotlib.use("Agg")

        tmp_dir = Path.cwd() / "test_output_receiver_window_backend"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        window = None
        try:
            from unittest import mock

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with mock.patch.object(plt, "get_backend", return_value="TkAgg"):
                    window = LiveWaterfallWindow(
                        WaterfallConfig(
                            output_path=str(tmp_dir / "unused.png"),
                            sample_rate=48_000,
                            percentile_min=20.0,
                            percentile_max=99.8,
                        )
                    )

            self.assertTrue(window._is_interactive_backend)
        finally:
            if window is not None:
                window.close()
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_candidate_fixture_writes_all_review_artifacts(self):
        audio_sample_rate = 48_000
        block_size = 4_096
        signal = meteor_candidate_fixture(audio_sample_rate)
        tmp_dir = Path.cwd() / "test_output_detector_artifacts"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            detector = MeteorDetector(
                DetectorConfig(
                    sample_rate=audio_sample_rate,
                    block_size=block_size,
                    output_dir=str(tmp_dir),
                    save_spectrogram=True,
                    save_wav=True,
                    save_detection_waterfall=True,
                ),
                print_fn=lambda _: None,
                detection_waterfall_saver=lambda path, config: _write_placeholder_snapshot(path),
            )
            events = []
            timestamp = 0.0
            padded = np.pad(signal, (0, (-signal.size) % block_size))
            for start in range(0, padded.size, block_size):
                block = padded[start : start + block_size]
                timestamp += block.size / audio_sample_rate
                events.extend(detector.process_block(block, timestamp=timestamp))
            events.extend(detector.finalize_pending(timestamp=timestamp + 0.2))

            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(event.event_type, "meteor_candidate")
            self.assertTrue(Path(event.image_file).exists())
            self.assertTrue(Path(event.wav_file).exists())
            self.assertTrue(Path(event.waterfall_file).exists())
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _write_placeholder_snapshot(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"png")
    return str(path)


if __name__ == "__main__":
    unittest.main()
