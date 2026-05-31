import queue
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from meteor_station.audio_input import AudioBlockAccumulator, InputDeviceInfo, resolve_input_device
from meteor_station.config import load_audio_input_config, load_local_sdrsharp_runtime_config


class AudioInputTests(unittest.TestCase):
    def test_resolve_input_device_by_index(self):
        devices = [
            InputDeviceInfo(index=3, name="Microphone", max_input_channels=2, default_samplerate=48000.0),
            InputDeviceInfo(index=20, name="CABLE Output", max_input_channels=2, default_samplerate=48000.0),
        ]
        resolved = resolve_input_device(device_index=20, devices=devices)
        self.assertEqual(resolved.name, "CABLE Output")

    def test_resolve_input_device_by_name(self):
        devices = [
            InputDeviceInfo(index=3, name="Microphone", max_input_channels=2, default_samplerate=48000.0),
            InputDeviceInfo(index=20, name="CABLE Output (VB-Audio)", max_input_channels=2, default_samplerate=48000.0),
        ]
        resolved = resolve_input_device(device_name_contains="vb-audio", devices=devices)
        self.assertEqual(resolved.index, 20)

    def test_resolve_input_device_fails_on_ambiguous_name(self):
        devices = [
            InputDeviceInfo(index=20, name="CABLE Output A", max_input_channels=2, default_samplerate=48000.0),
            InputDeviceInfo(index=21, name="CABLE Output B", max_input_channels=2, default_samplerate=48000.0),
        ]
        with self.assertRaisesRegex(ValueError, "matched multiple devices"):
            resolve_input_device(device_name_contains="cable output", devices=devices)

    def test_audio_block_accumulator_reassembles_stereo_chunks(self):
        accumulator = AudioBlockAccumulator(
            block_size=4,
            channels=2,
            queue_max_blocks=8,
        )
        first = np.array([[1.0, 3.0], [2.0, 4.0], [5.0, 7.0]], dtype=np.float32)
        second = np.array([[6.0, 8.0], [9.0, 11.0], [10.0, 12.0]], dtype=np.float32)

        accumulator.append_frames(first)
        accumulator.append_frames(second)

        block = accumulator.next_block(timeout=0.1)
        self.assertIsNotNone(block)
        np.testing.assert_allclose(block, np.array([2.0, 3.0, 6.0, 7.0], dtype=np.float32))
        np.testing.assert_allclose(accumulator.drain_partial_block(), np.array([10.0, 11.0], dtype=np.float32))

    def test_audio_block_accumulator_reports_status_and_overflow(self):
        timestamps = iter([100.0, 100.0, 120.0])
        accumulator = AudioBlockAccumulator(
            block_size=2,
            channels=1,
            queue_max_blocks=1,
            status_warning_interval_s=10.0,
            time_provider=lambda: next(timestamps),
        )

        accumulator.append_frames(np.array([0.1, 0.2], dtype=np.float32), status="overflow")
        accumulator.append_frames(np.array([0.3, 0.4], dtype=np.float32), status="overflow")
        messages = accumulator.pop_status_messages()

        self.assertEqual(messages[0], "Audio callback status: overflow")
        self.assertIn("dropped 1 block", messages[1])

    def test_load_local_audio_config_defaults(self):
        profile = load_audio_input_config()
        runtime = load_local_sdrsharp_runtime_config()

        self.assertEqual(profile.device_name_contains, "CABLE Output")
        self.assertEqual(profile.sample_rate, 48_000)
        self.assertEqual(profile.block_size, 4_096)
        self.assertTrue(runtime.save_spectrogram)
        self.assertEqual(runtime.waterfall_path, "live_waterfall.png")


if __name__ == "__main__":
    unittest.main()
