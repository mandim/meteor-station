from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .detector import MeteorDetector, MeteorEvent
from .dsp import UsbDemodulator, UsbDemodulatorConfig, rtl_tcp_bytes_to_iq
from .streaming import RtlTcpClient


class AudioSink(Protocol):
    def consume_block(self, block: np.ndarray, *, start_timestamp: float, sample_rate: int) -> None: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...


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
    def __init__(
        self,
        config: ReceiverConfig,
        detector: MeteorDetector,
        *,
        audio_sinks: list[AudioSink] | None = None,
    ) -> None:
        self.config = config
        self.detector = detector
        self.audio_sinks = audio_sinks or []
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
        start_timestamp: float | None = None,
    ) -> list[MeteorEvent]:
        events: list[MeteorEvent] = []
        timestamp = time.time() if start_timestamp is None else start_timestamp
        for block in self.demodulator.process_iq(iq_samples):
            block_start = timestamp
            timestamp += block.size / self.config.audio_sample_rate
            self._publish_audio_block(block, block_start)
            events.extend(self.detector.process_block(block, timestamp=timestamp))
        return events

    def process_rtl_payload(
        self,
        payload: bytes,
        *,
        start_timestamp: float | None = None,
    ) -> list[MeteorEvent]:
        return self.process_iq_samples(rtl_tcp_bytes_to_iq(payload), start_timestamp=start_timestamp)

    def flush(self, timestamp: float) -> list[MeteorEvent]:
        events: list[MeteorEvent] = []
        for block in self.demodulator.flush():
            block_start = timestamp
            timestamp += block.size / self.config.audio_sample_rate
            self._publish_audio_block(block, block_start)
            events.extend(self.detector.process_block(block, timestamp=timestamp))
        events.extend(self.detector.finalize_pending(timestamp=timestamp))
        self._flush_audio_sinks()
        return events

    def run_forever(self, *, stop_event: threading.Event | None = None) -> None:
        client = RtlTcpClient(
            self.config.server_host,
            self.config.server_port,
            chunk_size=self.config.iq_chunk_bytes,
            timeout_s=0.5,
        )
        stream_time = time.time()
        try:
            client.connect()
            for payload in client.iter_chunks():
                if stop_event is not None and stop_event.is_set():
                    break
                iq_samples = rtl_tcp_bytes_to_iq(payload)
                for block in self.demodulator.process_iq(iq_samples):
                    if stop_event is not None and stop_event.is_set():
                        break
                    block_start = stream_time
                    stream_time += block.size / self.config.audio_sample_rate
                    self._publish_audio_block(block, block_start)
                    self.detector.process_block(block, timestamp=stream_time)
                if stop_event is not None and stop_event.is_set():
                    break
        finally:
            try:
                self.flush(stream_time)
            finally:
                self._close_audio_sinks()
                client.close()

    def _publish_audio_block(self, block: np.ndarray, start_timestamp: float) -> None:
        for sink in self.audio_sinks:
            sink.consume_block(
                block,
                start_timestamp=start_timestamp,
                sample_rate=self.config.audio_sample_rate,
            )

    def _flush_audio_sinks(self) -> None:
        for sink in self.audio_sinks:
            sink.flush()

    def _close_audio_sinks(self) -> None:
        for sink in self.audio_sinks:
            sink.close()
