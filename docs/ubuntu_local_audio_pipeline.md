# Ubuntu Local Audio Detection on LattePanda or PC

This guide covers the Ubuntu local-audio workflow. It assumes a Linux SDR or demodulation chain feeds a monitor or loopback input that `sounddevice` can read.

Related docs:
- [Operator Guide](/C:/Users/mandi/Desktop/meteor_station/docs/operator_guide.md)
- [Windows SDR# Local Detection](/C:/Users/mandi/Desktop/meteor_station/docs/sdrsharp_local_pipeline.md)
- [LAN Streaming](/C:/Users/mandi/Desktop/meteor_station/docs/lan_streaming.md)

## Overview
- An SDR application or CLI demodulator runs on Ubuntu.
- Its audio is routed to an ALSA/PipeWire monitor or loopback input.
- `meteor-station-sdrsharp-detect` reads that Linux input device and runs the detector.

Despite the command name, this is the supported local-audio detector entrypoint for both Windows and Linux.

## Prerequisites
- Ubuntu `22.04+` or another recent Linux distribution with PipeWire or PulseAudio compatibility
- Python `3.10+`
- A working SDR or demod chain that already produces audio near the GRAVES offset
- Repo dependencies installed

Install base packages:

```bash
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv portaudio19-dev ffmpeg
```

Install the repo:

```bash
git clone YOUR_REPO_URL ~/meteor_station
cd ~/meteor_station
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
cp meteor_station.example.toml meteor_station.toml
```

## Audio Routing
Use a monitor or loopback source, not the speaker sink directly.

Useful checks:

```bash
pactl list short sources
pactl list short sinks
pw-link -l
```

Typical options:
- a PipeWire monitor source such as `alsa_output...monitor`
- an explicit null sink plus its monitor source
- an ALSA loopback device if you are using `snd-aloop`

If needed, create a null sink:

```bash
pactl load-module module-null-sink sink_name=meteor_monitor sink_properties=device.description=meteor_monitor
```

Then route your SDR app or demod chain into that sink and capture from its monitor source.

## Discover the Input Device
List devices that `sounddevice` can open:

```bash
source .venv/bin/activate
meteor-station-sdrsharp-detect --list-audio-devices
```

Pick either:
- a stable `device_index`
- or a `device_name_contains` substring such as `Monitor`

## Config Example
Use dedicated Ubuntu profiles:

```toml
[audio_inputs.ubuntu_loopback]
device_name_contains = "Monitor"
sample_rate = 48000
channels = 1
block_size = 4096
dtype = "float32"
queue_max_blocks = 128

[runtime.ubuntu_local_audio]
output_dir = "meteor_logs"
save_spectrogram = true
save_wav = true
save_detection_waterfall = true
waterfall_path = "live_waterfall.png"

[detector_profiles.graves_sdrsharp_v4]
detector_mode = "v4"
```

`device_index` takes priority if you set both.

## Run Live Detection
Current detector behavior:

```bash
source .venv/bin/activate
meteor-station-sdrsharp-detect \
  --config meteor_station.toml \
  --audio-input-profile ubuntu_loopback \
  --runtime-profile ubuntu_local_audio \
  --detector-profile graves_sdrsharp
```

Stricter detector:

```bash
source .venv/bin/activate
meteor-station-sdrsharp-detect \
  --config meteor_station.toml \
  --audio-input-profile ubuntu_loopback \
  --runtime-profile ubuntu_local_audio \
  --detector-profile graves_sdrsharp_v4
```

If you already use a `v3` detector profile and only want the new scorer:

```bash
meteor-station-sdrsharp-detect \
  --config meteor_station.toml \
  --audio-input-profile ubuntu_loopback \
  --runtime-profile ubuntu_local_audio \
  --detector-profile graves_sdrsharp \
  --detector-mode v4
```

## Offline Validation
Validate the Linux detector path against a saved WAV:

```bash
meteor-station-sdrsharp-detect \
  --config meteor_station.toml \
  --audio-input-profile ubuntu_loopback \
  --runtime-profile ubuntu_local_audio \
  --detector-profile graves_sdrsharp_v4 \
  --input-wav /path/to/fixture.wav
```

## Platform-Specific Troubleshooting
- If `--list-audio-devices` does not show your loopback source, confirm the source exists with `pactl list short sources`.
- If the detector opens the wrong input, prefer a stable substring or pin the device index once you confirm it.
- If there are callback overruns, increase `queue_max_blocks` and reduce CPU-heavy desktop activity.
- If the waterfall shows broadband vertical streaks, compare `graves_sdrsharp` and `graves_sdrsharp_v4` on the same WAV before changing thresholds.
- If the signal is visible in your SDR app but not in detector artifacts, verify that the captured monitor source is the one carrying demodulated USB audio.
