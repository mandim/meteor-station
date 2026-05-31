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

The config now has two relevant sections:

- `[profiles.graves]` for RF/IQ streaming settings
- `[detector_profiles.graves]` for the tuned GRAVES detector thresholds and review-artifact settings

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

#### Windows with Conda

Create and activate a Conda environment for the PC receiver:

```powershell
conda create -n meteor python=3.11 -y
conda activate meteor
python -m pip install --upgrade pip
python -m pip install -e .
```

The repo also includes [run_detector.ps1](/C:/Users/mandi/Desktop/meteor_station/run_detector.ps1:1) and [run_pc_receiver.ps1](/C:/Users/mandi/Desktop/meteor_station/run_pc_receiver.ps1:1), which prefer:

- the currently activated Conda environment via `$env:CONDA_PREFIX`
- or a `meteor` environment in standard Anaconda/Miniconda locations

#### Linux/macOS or plain Python

```bash
python -m venv .venv
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
  --detector-profile graves \
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

- `--detector-profile NAME` to select a named detector profile from `[detector_profiles.*]`
- `--save-wav` to force-enable WAV captures for `meteor_candidate` events
- `--no-wav` to disable WAV captures if you do not want review audio files
- `--no-spectrogram` to disable PNG output
- `--no-detection-waterfall` to disable the per-detection rolling-waterfall snapshot PNG
- `--detection-waterfall-dir NAME` to change the subdirectory under `--output-dir` used for detection snapshots. Default: `waterfalls`
- `--detection-waterfall-prefix PREFIX` to change the detection snapshot filename prefix. Default: `event_v3_`
- `--listen-audio` to hear the demodulated GRAVES audio on the PC speakers
- `--show-waterfall` to open a live waterfall window on the PC
- `--audio-output-device INDEX` to choose a specific output device for monitoring
- `--waterfall-path PATH` to write the rolling waterfall PNG somewhere other than `meteor_logs/live_waterfall.png`
- `--waterfall-window-seconds` and `--waterfall-update-seconds` to control the waterfall history depth and refresh rate
- `--detection-min-hz` and `--detection-max-hz` if you want to experiment with the v3 audio band

Default behavior:

- the `graves` detector profile is loaded from `[detector_profiles.graves]` in `meteor_station.toml`
- candidate WAV capture is enabled by default
- when a `meteor_candidate` event is finalized, the detector saves:
  `event_v3_XXXXX.png` as a narrow review spectrogram cropped to the GRAVES audio band
  `waterfalls/event_v3_XXXXX.png` as a short review waterfall snapshot separate from `live_waterfall.png`
  `event_v3_XXXXX.wav` as the demodulated review audio unless disabled with `--no-wav`
- `live_waterfall.png` continues to be refreshed in place as the operator overview waterfall

### Windows PowerShell example with Conda

```powershell
conda activate meteor
meteor-station-pc-detect `
  --config meteor_station.toml `
  --detector-profile graves `
  --server-host 192.168.1.50 `
  --server-port 1234 `
  --center-freq-hz 143048400 `
  --vfo-hz 143048400 `
  --usb-bandwidth-hz 3000 `
  --iq-sample-rate 240000 `
  --audio-sample-rate 48000 `
  --output-dir meteor_logs
```

### Windows PowerShell example using the dedicated receiver wrapper

This is the shortest normal Windows startup path:

```powershell
conda activate meteor
.\run_pc_receiver.ps1 -Config meteor_station.toml -ServerHost 192.168.1.50
```

Equivalent full form:

```powershell
conda activate meteor
.\run_pc_receiver.ps1 `
  -Config meteor_station.toml `
  -DetectorProfile graves `
  -ServerHost 192.168.1.50 `
  -ServerPort 1234 `
  -CenterFreqHz 143048400 `
  -VfoHz 143048400 `
  -UsbBandwidthHz 3000 `
  -IqSampleRate 240000 `
  -AudioSampleRate 48000 `
  -OutputDir meteor_logs `
  -ListenAudio `
  -ShowWaterfall `
  -WaterfallPath meteor_logs\live_waterfall.png
```

Note:

- `run_pc_receiver.ps1` now exposes `-DetectorProfile`, `-SaveWav`, `-NoWav`, and `-NoDetectionWaterfall`
- if you want to change `--detection-waterfall-dir` or `--detection-waterfall-prefix`, run `meteor-station-pc-detect` directly

If your Conda environment is not named `meteor`, either activate it first or set:

```powershell
$env:METEOR_PYTHON = "C:\full\path\to\python.exe"
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
- `event_v3_XXXXX.png`: review spectrograms for `meteor_candidate` detections, cropped to the configured GRAVES review band
- `waterfalls/event_v3_XXXXX.png`: short review waterfall snapshots saved when a `meteor_candidate` detection is finalized
- `event_v3_XXXXX.wav`: demodulated review WAV captures for `meteor_candidate` detections unless disabled with `--no-wav`
- `live_waterfall.png`: rolling waterfall of the demodulated audio with UTC time labels

The CSV now includes separate artifact paths:

- `image_file`: event-only spectrogram PNG
- `waterfall_file`: detection-triggered review-waterfall snapshot PNG
- `wav_file`: review WAV capture path

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
- startup banner also prints the detector profile, active detection band, and whether WAV / detection-triggered waterfall review artifacts are enabled
- `meteor_logs/events_v3.csv` is created on startup
- `meteor_logs/live_waterfall.png` is updated while the receiver is running
- when `meteor_candidate` events are logged, the corresponding review artifacts appear:
  `meteor_logs/event_v3_XXXXX.png` for the event spectrogram
  `meteor_logs/waterfalls/event_v3_XXXXX.png` for the short review-waterfall snapshot
  `meteor_logs/event_v3_XXXXX.wav` for the demodulated review audio unless disabled

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
