import csv
import io
import shutil
import sys
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from fixtures import meteor_candidate_fixture
from meteor_station.cli import sdrsharp_detect


def write_wav(path: Path, signal: np.ndarray, sample_rate: int) -> None:
    pcm16 = np.clip(signal, -1.0, 1.0)
    pcm16 = (pcm16 * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm16.tobytes())


class SdrsharpCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sample_rate = 48_000
        self.tmp_dir = Path.cwd() / "test_output_sdrsharp_cli"
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_list_audio_devices_prints_available_inputs(self):
        fake_devices = [
            mock.Mock(index=20, name="CABLE Output (VB-Audio)", max_input_channels=2, default_samplerate=48000.0),
        ]
        stdout = io.StringIO()
        argv = ["meteor-station-sdrsharp-detect", "--list-audio-devices"]
        with mock.patch("meteor_station.cli.sdrsharp_detect.list_input_devices", return_value=fake_devices):
            with mock.patch.object(sys, "argv", argv):
                with mock.patch("sys.stdout", stdout):
                    exit_code = sdrsharp_detect.main()

        self.assertEqual(exit_code, 0)
        self.assertIn("CABLE Output (VB-Audio)", stdout.getvalue())

    def test_wav_mode_writes_review_artifacts(self):
        wav_path = self.tmp_dir / "candidate.wav"
        output_dir = self.tmp_dir / "output"
        write_wav(wav_path, meteor_candidate_fixture(self.sample_rate), self.sample_rate)

        stdout = io.StringIO()
        argv = [
            "meteor-station-sdrsharp-detect",
            "--input-wav",
            str(wav_path),
            "--output-dir",
            str(output_dir),
        ]
        with mock.patch.object(sys, "argv", argv):
            with mock.patch("sys.stdout", stdout):
                exit_code = sdrsharp_detect.main()

        self.assertEqual(exit_code, 0)
        csv_path = output_dir / "events_v3.csv"
        with csv_path.open(encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][12], "meteor_candidate")
        self.assertTrue(Path(rows[1][13]).exists())
        self.assertTrue(Path(rows[1][14]).exists())
        self.assertTrue(Path(rows[1][15]).exists())

    def test_cli_overrides_can_disable_wav_artifact(self):
        wav_path = self.tmp_dir / "candidate_nowav.wav"
        output_dir = self.tmp_dir / "override_output"
        config_path = self.tmp_dir / "override.toml"
        write_wav(wav_path, meteor_candidate_fixture(self.sample_rate), self.sample_rate)
        config_path.write_text(
            "\n".join(
                [
                    "[runtime.local_sdrsharp]",
                    f'output_dir = "{(self.tmp_dir / "from_config").as_posix()}"',
                    "save_wav = true",
                ]
            ),
            encoding="utf-8",
        )

        argv = [
            "meteor-station-sdrsharp-detect",
            "--config",
            str(config_path),
            "--input-wav",
            str(wav_path),
            "--output-dir",
            str(output_dir),
            "--no-wav",
        ]
        with mock.patch.object(sys, "argv", argv):
            exit_code = sdrsharp_detect.main()

        self.assertEqual(exit_code, 0)
        csv_path = output_dir / "events_v3.csv"
        with csv_path.open(encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(rows[1][15], "")
        self.assertFalse((output_dir / "event_v3_00001.wav").exists())
        self.assertFalse((self.tmp_dir / "from_config" / "events_v3.csv").exists())

    def test_detector_mode_override_uses_v4_outputs(self):
        wav_path = self.tmp_dir / "candidate_v4.wav"
        output_dir = self.tmp_dir / "v4_output"
        write_wav(wav_path, meteor_candidate_fixture(self.sample_rate), self.sample_rate)

        argv = [
            "meteor-station-sdrsharp-detect",
            "--input-wav",
            str(wav_path),
            "--output-dir",
            str(output_dir),
            "--detector-mode",
            "v4",
        ]
        with mock.patch.object(sys, "argv", argv):
            exit_code = sdrsharp_detect.main()

        self.assertEqual(exit_code, 0)
        with (output_dir / "events_v3.csv").open(encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(rows[1][23], "v4")
        self.assertTrue((output_dir / "event_v4_00001.png").exists())


if __name__ == "__main__":
    unittest.main()
