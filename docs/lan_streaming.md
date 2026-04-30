# LAN-Streamed RTL-SDR Meteor Station

This project runs in two parts:

1. A Raspberry Pi hosts the RTL-SDR dongle and publishes raw IQ samples over the LAN with `rtl_tcp`.
2. A PC on the same LAN connects to that stream, demodulates the GRAVES USB audio tone, and runs the detector.

The examples below assume:

- GRAVES carrier: `143.050000 MHz`
- Pi/RTL center frequency: `143.048400 MHz`
- USB bandwidth: `3000 Hz`
- IQ sample rate: `240000`
- Detector audio sample rate: `48000`
- RTL-TCP port: `1234`

## 1. Raspberry Pi setup

Use Raspberry Pi OS with network access and an attached RTL-SDR dongle.

### Install system packages

```bash
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv rtl-sdr
```

If the kernel DVB driver grabs the dongle, blacklist it and reboot:

```bash
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/rtl-sdr-blacklist.conf
sudo reboot
```

After reboot, confirm the dongle is visible:

```bash
rtl_test -t
```

### Install the repo on the Pi

Choose an install path, for example `/opt/meteor_station`:

```bash
sudo mkdir -p /opt/meteor_station
sudo chown "$USER":"$USER" /opt/meteor_station
git clone YOUR_REPO_URL /opt/meteor_station
cd /opt/meteor_station
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Copy the sample config and adjust values if needed:

```bash
cp meteor_station.example.toml meteor_station.toml
```

### Run the Pi streamer manually

From the repo root:

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

Expected result:

- `rtl_tcp` starts and binds to `0.0.0.0:1234`
- the Pi keeps running until interrupted
- the PC can connect over the LAN

### Install the Pi streamer as a `systemd` service

Create `/etc/systemd/system/meteor-station-pi-stream.service`:

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

Change `User=pi` if your Pi user is different.

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable meteor-station-pi-stream.service
sudo systemctl start meteor-station-pi-stream.service
```

Check status and logs:

```bash
sudo systemctl status meteor-station-pi-stream.service
journalctl -u meteor-station-pi-stream.service -f
```

Useful service commands:

```bash
sudo systemctl restart meteor-station-pi-stream.service
sudo systemctl stop meteor-station-pi-stream.service
sudo systemctl disable meteor-station-pi-stream.service
```

## 2. PC receiver setup

The PC runs the DSP and detector. It does not need SDR# or VB-CABLE for this pipeline.

### Install Python environment

From the repo root on the PC:

```bash
python -m venv .venv
```

On Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

On Linux/macOS:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Copy the sample config:

```bash
cp meteor_station.example.toml meteor_station.toml
```

### Run the PC receiver manually

Replace `PI_LAN_IP` with the Raspberry Pi address:

```bash
meteor-station-pc-detect \
  --config meteor_station.toml \
  --server-host PI_LAN_IP \
  --server-port 1234 \
  --center-freq-hz 143048400 \
  --vfo-hz 143048400 \
  --usb-bandwidth-hz 3000 \
  --iq-sample-rate 240000 \
  --audio-sample-rate 48000 \
  --output-dir meteor_logs
```

Optional flags:

- `--save-wav` to save WAV captures for `meteor_candidate` events
- `--no-spectrogram` to disable PNG output
- `--detection-min-hz` and `--detection-max-hz` if you want to experiment with the v3 audio band

### Windows PowerShell example

```powershell
.venv\Scripts\Activate.ps1
meteor-station-pc-detect `
  --config meteor_station.toml `
  --server-host 192.168.1.50 `
  --server-port 1234 `
  --center-freq-hz 143048400 `
  --vfo-hz 143048400 `
  --usb-bandwidth-hz 3000 `
  --iq-sample-rate 240000 `
  --audio-sample-rate 48000 `
  --output-dir meteor_logs
```

## 3. End-to-end startup order

1. Plug the RTL-SDR into the Raspberry Pi.
2. Start the Pi service:
   `sudo systemctl start meteor-station-pi-stream.service`
3. Confirm the service is healthy:
   `sudo systemctl status meteor-station-pi-stream.service`
4. On the PC, activate the Python environment.
5. Start `meteor-station-pc-detect`.
6. Watch the PC console for detector startup messages and event lines.

## 4. Output locations

By default the PC writes detector outputs into `meteor_logs/` under the current working directory:

- `events_v3.csv`: structured event log
- `event_v3_XXXXX.png`: spectrograms for `meteor_candidate` detections
- `event_v3_XXXXX.wav`: optional WAV captures if `--save-wav` is enabled

If you want outputs somewhere else, pass `--output-dir`.

## 5. Verification checklist

### Pi-side checks

```bash
rtl_test -t
sudo systemctl status meteor-station-pi-stream.service
ss -ltnp | grep 1234
```

### PC-side checks

- startup banner prints the configured server, center frequency, VFO, bandwidth, and output directory
- `meteor_logs/events_v3.csv` is created on startup
- PNG files appear when `meteor_candidate` events are logged

### If the PC cannot connect

Check:

- Pi IP address is correct
- the service is running
- port `1234` is reachable through the LAN/firewall
- `rtl_tcp` is not already running in another session

## 6. Updating after code changes

On either machine:

```bash
cd /opt/meteor_station   # or your local clone path
git pull
source .venv/bin/activate
python -m pip install -e .
```

If the Pi service is installed, restart it:

```bash
sudo systemctl restart meteor-station-pi-stream.service
```
