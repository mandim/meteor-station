# SDR# Local Detection Pipeline

## Overview
This pipeline runs entirely on the same Windows mini PC:

- `SDR#` tunes the receiver and outputs demodulated USB audio.
- `VB-CABLE` exposes that audio as a Windows recording device.
- `meteor-station-sdrsharp-detect` reads that local audio input.
- The detector writes event logs and review artifacts to disk on the same machine.

There is no `rtl_tcp`, no network hop, and no Raspberry Pi in this workflow.

## Prerequisites
- Windows on the LattePanda Alpha
- Python 3.10 or newer
- SDR#
- VB-CABLE installed and visible in Windows audio devices
- Python dependencies installed from this repo:

```powershell
python -m pip install -e .
```

## One-Time Setup
### 1. Configure SDR#
Use the tuned GRAVES assumptions from the original SDR# workflow:

- Mode: `USB`
- RF tuned frequency / VFO: `143.048400 MHz`
- Expected carrier: `143.050000 MHz`
- Audio offset of interest: about `1600 Hz`
- Bandwidth: `3.000 kHz`

The detector default profile `graves_sdrsharp` is set up for that audio band and trigger behavior.

### 2. Configure VB-CABLE
- In SDR#, route audio output to the VB-CABLE playback device.
- In Windows, confirm the matching VB-CABLE recording/input device exists.
- Keep the Windows audio path at `48000 Hz` if possible.

### 3. List usable input devices
Run:

```powershell
meteor-station-sdrsharp-detect --list-audio-devices
```

Find the VB-CABLE input device. Record either:

- its numeric device index, or
- a stable substring from its name, such as `CABLE Output`

### 4. Configure `meteor_station.toml`
Copy the example if needed:

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
log_level = "INFO"
save_spectrogram = true
save_wav = true
save_detection_waterfall = true
waterfall_path = "live_waterfall.png"

[detector_profiles.graves_sdrsharp]
detection_min_hz = 1200
detection_max_hz = 1600
trigger_db_above_baseline = 11.0
band_rise_db_min = 3.0
peak_to_median_db_min = 6.5
max_near_peak_bins = 5
```

Notes:
- `device_index` takes priority over `device_name_contains`.
- `waterfall_path` is relative to `output_dir` unless you provide an absolute path.
- `block_size` and `sample_rate` should normally stay at `4096` and `48000`.

## Daily Use
### Start live detection

```powershell
meteor-station-sdrsharp-detect --config meteor_station.toml
```

Typical startup output shows:

- live vs WAV mode
- sample rate
- block size
- output directory
- detection band
- artifact flags
- selected input device

### Override settings from the command line
Examples:

```powershell
meteor-station-sdrsharp-detect --config meteor_station.toml --device-index 18
meteor-station-sdrsharp-detect --config meteor_station.toml --device-name "CABLE Output"
meteor-station-sdrsharp-detect --config meteor_station.toml --output-dir D:\meteor_logs
meteor-station-sdrsharp-detect --config meteor_station.toml --no-wav
```

### Stop the detector
Press `Ctrl+C`.

The detector will stop the input stream and finalize any pending event state before exit.

## Output Files
By default outputs go to `meteor_logs/`.

Expected files:
- `events_v3.csv`: structured event log
- `event_v3_00001.png`: saved spectrogram for a meteor candidate
- `event_v3_00001.wav`: saved review audio for a meteor candidate
- `live_waterfall.png`: rolling waterfall image
- `waterfalls/event_v3_00001.png`: candidate review waterfall snapshot

Only `meteor_candidate` events create review artifacts. Rejected events still appear in the CSV.

## Offline Validation with a WAV File
You can validate the exact detector path without SDR# running:

```powershell
meteor-station-sdrsharp-detect --config meteor_station.toml --input-wav C:\path\to\fixture.wav
```

Use this to:
- verify config changes against a known recording
- test artifact generation
- compare false positives and threshold changes

The WAV file must match the configured sample rate, normally `48000 Hz`.

## Troubleshooting
### No audio arriving
- Confirm SDR# is sending audio to VB-CABLE, not your speakers.
- Confirm the Python process is reading the VB-CABLE input device, not a microphone.
- Run `--list-audio-devices` again and re-check the device index after reboots or driver changes.

### Wrong device selected
- Prefer `device_index` once the correct device is known.
- If the index changes often, remove `device_index` and rely on `device_name_contains`.

### Sample-rate mismatch
- Keep SDR#, Windows device settings, and the detector config aligned at `48000 Hz`.
- WAV mode will fail fast if the file sample rate does not match the configured rate.

### No detections despite a visible carrier
- Confirm SDR# is in `USB` mode.
- Confirm the carrier lands near the detector band `1200-1600 Hz`.
- Check that the tuned SDR# frequency still matches the expected GRAVES offset.
- Review whether the signal is present in `live_waterfall.png`.

### Too many false positives
- Tighten detector thresholds in `[detector_profiles.graves_sdrsharp]`.
- Start with `trigger_db_above_baseline`, `peak_to_median_db_min`, and `max_near_peak_bins`.
- Validate changes first with `--input-wav` before trusting a live run.

### Callback overflow or dropped audio
- Look for `WARNING:` lines in the console.
- Increase `queue_max_blocks`.
- Reduce background CPU load on the LattePanda Alpha.
- Avoid running heavy GUI tasks on the same machine during continuous monitoring.

## Configuration Reference
### `[audio_inputs.sdrsharp_vb_cable]`
- `device_index`: exact Windows input device index
- `device_name_contains`: fallback substring match
- `sample_rate`: expected audio sample rate
- `channels`: input channels from the Windows device
- `block_size`: detector block size
- `dtype`: `sounddevice` input sample format
- `queue_max_blocks`: backlog size before audio blocks are dropped

### `[runtime.local_sdrsharp]`
- `output_dir`: root directory for logs and artifacts
- `log_level`: reserved runtime verbosity field
- `save_spectrogram`: enable candidate spectrogram PNGs
- `save_wav`: enable candidate WAV review files
- `save_detection_waterfall`: enable rolling waterfall and candidate snapshot output
- `waterfall_path`: rolling waterfall PNG path

### `[detector_profiles.graves_sdrsharp]`
This holds the tuned meteor detection thresholds. Treat it as the algorithm profile, not as device config.
