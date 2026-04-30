import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from meteor_station.dsp import UsbDemodulator, UsbDemodulatorConfig


def fft_peak_hz(signal: np.ndarray, sample_rate: int) -> float:
    spectrum = np.fft.rfft(signal * np.hanning(signal.size))
    freqs = np.fft.rfftfreq(signal.size, d=1.0 / sample_rate)
    return float(freqs[int(np.argmax(np.abs(spectrum)))])


class DspTests(unittest.TestCase):
    def _render_audio(self, iq: np.ndarray, config: UsbDemodulatorConfig) -> np.ndarray:
        demod = UsbDemodulator(config)
        blocks = demod.process_iq(iq)
        blocks.extend(demod.flush())
        return np.concatenate(blocks)

    def test_demodulator_preserves_expected_usb_tone(self):
        sample_rate = 240_000
        duration_s = 1.0
        tone_hz = 1_600.0
        t = np.arange(int(sample_rate * duration_s), dtype=np.float32) / sample_rate
        iq = np.exp(1j * 2.0 * np.pi * tone_hz * t).astype(np.complex64)
        audio = self._render_audio(
            iq,
            UsbDemodulatorConfig(
                input_sample_rate=sample_rate,
                output_sample_rate=48_000,
                center_freq_hz=143_048_400,
                vfo_hz=143_048_400,
                usb_bandwidth_hz=3_000,
                block_size=4_096,
            ),
        )
        peak_hz = fft_peak_hz(audio[: 48_000], 48_000)
        self.assertAlmostEqual(peak_hz, 1600.0, delta=40.0)

    def test_lowpass_rejects_out_of_band_tone(self):
        sample_rate = 240_000
        duration_s = 1.0
        t = np.arange(int(sample_rate * duration_s), dtype=np.float32) / sample_rate
        iq = (
            np.exp(1j * 2.0 * np.pi * 1_600.0 * t)
            + 0.7 * np.exp(1j * 2.0 * np.pi * 5_000.0 * t)
        ).astype(np.complex64)
        audio = self._render_audio(
            iq,
            UsbDemodulatorConfig(
                input_sample_rate=sample_rate,
                output_sample_rate=48_000,
                center_freq_hz=143_048_400,
                vfo_hz=143_048_400,
                usb_bandwidth_hz=3_000,
                block_size=4_096,
            ),
        )[: 48_000]
        spectrum = np.abs(np.fft.rfft(audio * np.hanning(audio.size)))
        freqs = np.fft.rfftfreq(audio.size, d=1.0 / 48_000)
        mag_1600 = float(spectrum[np.argmin(np.abs(freqs - 1_600.0))])
        mag_5000 = float(spectrum[np.argmin(np.abs(freqs - 5_000.0))])
        self.assertGreater(mag_1600, mag_5000 * 5.0)


if __name__ == "__main__":
    unittest.main()
