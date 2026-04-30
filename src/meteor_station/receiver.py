from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .detector import MeteorDetector, MeteorEvent
from .dsp import UsbDemodulator, UsbDemodulatorConfig, rtl_tcp_bytes_to_iq
from .streaming import RtlTcpClient


@dataclass(slots=True)
class ReceiverConfig:
    server_host: str
    server_port: int
    iq_sample_rate: int
    audio_sample_rate: int
    center_freq_hz: int
    vfo_hz: int
    usb_bandwidth_hz: int
    iq_chunk_bytes: int = 16_384


class NetworkMeteorReceiver:
    def __init__(self, config: ReceiverConfig, detector: MeteorDetector) -> None:
        self.config = config
        self.detector = detector
        self.demodulator = UsbDemodulator(
            UsbDemodulatorConfig(
                input_sample_rate=config.iq_sample_rate,
                output_sample_rate=config.audio_sample_rate,
                usb_bandwidth_hz=config.usb_bandwidth_hz,
                center_freq_hz=config.center_freq_hz,
                vfo_hz=config.vfo_hz,
                block_size=detector.config.block_size,
            )
        )

    def process_iq_samples(
        self,
        iq_samples: np.ndarray,
        *,
        start_timestamp: float = 0.0,
    ) -> list[MeteorEvent]:
        events: list[MeteorEvent] = []
        timestamp = start_timestamp
        for block in self.demodulator.process_iq(iq_samples):
            timestamp += block.size / self.config.audio_sample_rate
            events.extend(self.detector.process_block(block, timestamp=timestamp))
        return events

    def process_rtl_payload(self, payload: bytes, *, start_timestamp: float = 0.0) -> list[MeteorEvent]:
        return self.process_iq_samples(rtl_tcp_bytes_to_iq(payload), start_timestamp=start_timestamp)

    def flush(self, timestamp: float) -> list[MeteorEvent]:
        events: list[MeteorEvent] = []
        for block in self.demodulator.flush():
            timestamp += block.size / self.config.audio_sample_rate
            events.extend(self.detector.process_block(block, timestamp=timestamp))
        events.extend(self.detector.finalize_pending(timestamp=timestamp))
        return events

    def run_forever(self) -> None:
        client = RtlTcpClient(
            self.config.server_host,
            self.config.server_port,
            chunk_size=self.config.iq_chunk_bytes,
        )
        stream_time = 0.0
        try:
            client.connect()
            for payload in client.iter_chunks():
                iq_samples = rtl_tcp_bytes_to_iq(payload)
                for block in self.demodulator.process_iq(iq_samples):
                    stream_time += block.size / self.config.audio_sample_rate
                    self.detector.process_block(block, timestamp=stream_time)
        finally:
            self.flush(stream_time)
            client.close()
