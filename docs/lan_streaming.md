# LAN-Streamed RTL-SDR Meteor Station

This workflow keeps the RTL-SDR on a Raspberry Pi and runs the detector on another machine that connects to `rtl_tcp`.

Related docs:
- [Operator Guide](/C:/Users/mandi/Desktop/meteor_station/docs/operator_guide.md)
- [Ubuntu Local Audio Setup](/C:/Users/mandi/Desktop/meteor_station/docs/ubuntu_local_audio_pipeline.md)
- [Windows SDR# Local Detection](/C:/Users/mandi/Desktop/meteor_station/docs/sdrsharp_local_pipeline.md)

## Overview
1. The Pi hosts the RTL-SDR and publishes raw IQ with `rtl_tcp`.
2. A PC connects to that IQ stream, demodulates the GRAVES USB tone, and runs the detector.

Examples below assume:
- GRAVES carrier: `143.050000 MHz`
- VFO / center frequency: `143.048400 MHz`
- USB bandwidth: `3000 Hz`
- IQ sample rate: `240000`
- Detector audio sample rate: `48000`
- `rtl_tcp` port: `1234`

## Raspberry Pi Setup
Install packages:

```bash
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv rtl-sdr
```

If the kernel DVB driver grabs the dongle:

```bash
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/rtl-sdr-blacklist.conf
sudo reboot
```

Confirm the dongle:

```bash
rtl_test -t
```

Install the repo:

```bash
git clone YOUR_REPO_URL /opt/meteor_station
cd /opt/meteor_station
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
cp meteor_station.example.toml meteor_station.toml
```

Run the Pi streamer:

```bash
source .venv/bin/activate
meteor-station-pi-stream \
  --config meteor_station.toml \
  --host 0.0.0.0 \
  --port 1234 \
  --center-freq 143048400 \
  --sample-rate 240000 \
  --gain 280 \
  --ppm 0
```

## Detector Side
Run the receiver on the PC or Ubuntu box:

```bash
meteor-station-pc-detect \
  --config meteor_station.toml \
  --server-host 192.168.1.50 \
  --detector-profile graves
```

To use the stricter detector path:

```bash
meteor-station-pc-detect \
  --config meteor_station.toml \
  --server-host 192.168.1.50 \
  --detector-profile graves_v4
```

Or override mode without changing profile names:

```bash
meteor-station-pc-detect --config meteor_station.toml --server-host 192.168.1.50 --detector-mode v4
```

## systemd Service
Example Pi service:

```ini
[Unit]
Description=Meteor Station RTL-SDR IQ Streamer
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/opt/meteor_station
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/meteor_station/.venv/bin/meteor-station-pi-stream --config /opt/meteor_station/meteor_station.toml --host 0.0.0.0 --port 1234 --center-freq 143048400 --sample-rate 240000 --gain 280 --ppm 0
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable meteor-station-pi-stream.service
sudo systemctl start meteor-station-pi-stream.service
```

## Outputs and Review
The receiver writes:
- `events_v3.csv`
- candidate PNG/WAV artifacts
- `live_waterfall.png`
- candidate waterfall snapshots in `waterfalls/`

Use [Operator Guide](/C:/Users/mandi/Desktop/meteor_station/docs/operator_guide.md) for command examples, output interpretation, and troubleshooting symptoms. Keep this document focused on the Pi-to-PC topology.
