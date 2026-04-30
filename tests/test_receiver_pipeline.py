import csv
import shutil
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from meteor_station.detector import DetectorConfig, MeteorDetector
from meteor_station.dsp import chunk_complex_samples
from meteor_station.receiver import NetworkMeteorReceiver, ReceiverConfig


class ReceiverPipelineTests(unittest.TestCase):
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
                    save_wav=False,
                    max_near_peak_bins=20,
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
            rows = list(csv.reader(open(csv_path, encoding="utf-8")))
            self.assertEqual(len(rows), 2)
            png_path = Path(rows[1][13])
            self.assertTrue(png_path.exists(), "expected spectrogram PNG to be created")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
