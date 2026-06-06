# SDR# Local Detection Pipeline

This guide is for the Windows-only SDR# and VB-CABLE workflow on a LattePanda or other mini PC.

Related docs:
- [Operator Guide](/C:/Users/mandi/Desktop/meteor_station/docs/operator_guide.md)
- [Ubuntu Local Audio Setup](/C:/Users/mandi/Desktop/meteor_station/docs/ubuntu_local_audio_pipeline.md)
- [LAN Streaming](/C:/Users/mandi/Desktop/meteor_station/docs/lan_streaming.md)

## Overview
- `SDR#` tunes the receiver and demodulates USB audio.
- `VB-CABLE` exposes that audio as a Windows recording device.
- `meteor-station-sdrsharp-detect` reads the local audio input and runs the detector.

There is no `rtl_tcp` hop in this workflow.

## Prerequisites
- Windows on the LattePanda or PC
- Python `3.10+`
- SDR#
- VB-CABLE installed and visible in Windows audio devices
- Repo dependencies installed:

```powershell
python -m pip install -e .
```

## One-Time Setup
### 1. Configure SDR#
Use the current GRAVES assumptions:

- Mode: `USB`
- VFO / tuned frequency: `143.048400 MHz`
- Expected carrier: `143.050000 MHz`
- Audio tone of interest: about `1600 Hz`
- Bandwidth: `3.000 kHz`

### 2. Configure VB-CABLE
- Route SDR# audio output to the VB-CABLE playback device.
- Confirm the matching VB-CABLE recording/input device exists in Windows.
- Keep the Windows audio path at `48000 Hz`.

### 3. List input devices

```powershell
meteor-station-sdrsharp-detect --list-audio-devices
```

Record either:
- the numeric `device_index`
- a stable substring such as `CABLE Output`

### 4. Prepare the config

```powershell
Copy-Item meteor_station.example.toml meteor_station.toml
```

Relevant sections:

```toml
[audio_inputs.sdrsharp_vb_cable]
device_index = 20
device_name_contains = "CABLE Output"
sample_rate = 48000
channels = 1
block_size = 4096
dtype = "float32"
queue_max_blocks = 128

[runtime.local_sdrsharp]
output_dir = "meteor_logs"
save_spectrogram = true
save_wav = true
save_detection_waterfall = true
waterfall_path = "live_waterfall.png"

[detector_profiles.graves_sdrsharp]
detector_mode = "v3"

[detector_profiles.graves_sdrsharp_v4]
detector_mode = "v4"
```

Notes:
- `device_index` takes priority over `device_name_contains`.
- `graves_sdrsharp` keeps the current detector behavior.
- `graves_sdrsharp_v4` enables the stricter false-positive-reduction path.

## Run Live Detection
Current detector:

```powershell
meteor-station-sdrsharp-detect `
  --config meteor_station.toml `
  --audio-input-profile sdrsharp_vb_cable `
  --runtime-profile local_sdrsharp `
  --detector-profile graves_sdrsharp
```

Stricter detector:

```powershell
meteor-station-sdrsharp-detect `
  --config meteor_station.toml `
  --audio-input-profile sdrsharp_vb_cable `
  --runtime-profile local_sdrsharp `
  --detector-profile graves_sdrsharp_v4
```

Equivalent one-off mode override:

```powershell
meteor-station-sdrsharp-detect --config meteor_station.toml --detector-profile graves_sdrsharp --detector-mode v4
```

## Offline Validation
Run the same detector path against a saved WAV:

```powershell
meteor-station-sdrsharp-detect `
  --config meteor_station.toml `
  --detector-profile graves_sdrsharp_v4 `
  --input-wav C:\path\to\fixture.wav
```

Use this to compare `v3` and `v4` on the same recording before trusting a live overnight run.

## Outputs
By default outputs go to `meteor_logs/`.

Expected files:
- `events_v3.csv`
- `event_v3_00001.png` or `event_v4_00001.png`
- `event_v3_00001.wav` or `event_v4_00001.wav`
- `live_waterfall.png`
- `waterfalls/event_v3_00001.png` or `waterfalls/event_v4_00001.png`

The CSV keeps the existing core columns and appends v4 review metrics such as `triggered_frames`, `active_ratio`, `band_energy_ratio`, `score`, `decision_reason`, and `detector_version`.

## Troubleshooting
Use the shared symptom-based guide in [Operator Guide](/C:/Users/mandi/Desktop/meteor_station/docs/operator_guide.md).

Windows-specific checks:
- If no audio arrives, confirm SDR# is feeding VB-CABLE rather than speakers.
- If the wrong device is selected, rerun `--list-audio-devices` after reboots or driver changes.
- If there are too many false positives, compare `graves_sdrsharp` against `graves_sdrsharp_v4` on the same WAV fixture before changing thresholds.
