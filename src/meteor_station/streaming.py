from __future__ import annotations

import shutil
import socket
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


RTL_TCP_INFO_HEADER_SIZE = 12


@dataclass(slots=True)
class RtlTcpLaunchConfig:
    host: str = "0.0.0.0"
    port: int = 1234
    device_index: int = 0
    sample_rate: int = 240_000
    center_freq: int = 143_048_400
    gain: int = 280
    ppm: int = 0
    rtl_tcp_path: str = "rtl_tcp"


@dataclass(slots=True)
class RtlTcpDongleInfo:
    tuner_type: int
    tuner_gain_count: int


class RtlTcpClient:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout_s: float = 5.0,
        chunk_size: int = 16_384,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout_s = timeout_s
        self.chunk_size = chunk_size
        self.sock: socket.socket | None = None
        self.dongle_info: RtlTcpDongleInfo | None = None

    def connect(self) -> None:
        if self.sock is not None:
            return
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout_s)
        header = self._recv_exact(sock, RTL_TCP_INFO_HEADER_SIZE)
        if header[:4] != b"RTL0":
            raise RuntimeError("Unexpected rtl_tcp header.")
        tuner_type, tuner_gain_count = struct.unpack(">II", header[4:])
        self.sock = sock
        self.dongle_info = RtlTcpDongleInfo(tuner_type=tuner_type, tuner_gain_count=tuner_gain_count)

    def iter_chunks(self) -> Iterator[bytes]:
        if self.sock is None:
            self.connect()
        assert self.sock is not None
        while True:
            try:
                payload = self.sock.recv(self.chunk_size)
            except TimeoutError:
                continue
            except socket.timeout:
                continue
            if not payload:
                break
            yield payload

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    @staticmethod
    def _recv_exact(sock: socket.socket, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            data = sock.recv(size - len(chunks))
            if not data:
                raise RuntimeError("Connection closed while reading rtl_tcp header.")
            chunks.extend(data)
        return bytes(chunks)


def launch_rtl_tcp(config: RtlTcpLaunchConfig) -> subprocess.Popen[str]:
    executable = shutil.which(config.rtl_tcp_path) or shutil.which(Path(config.rtl_tcp_path).name)
    if executable is None:
        raise FileNotFoundError(
            f"Could not find rtl_tcp executable '{config.rtl_tcp_path}'. Install rtl-sdr tools or pass --rtl-tcp-path."
        )
    args = [
        executable,
        "-a",
        config.host,
        "-p",
        str(config.port),
        "-d",
        str(config.device_index),
        "-s",
        str(config.sample_rate),
        "-f",
        str(config.center_freq),
        "-g",
        str(config.gain / 10.0),
        "-P",
        str(config.ppm),
    ]
    return subprocess.Popen(args)
