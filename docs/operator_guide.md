# Meteor Station Operator Guide

This is the day-to-day runbook for the packaged detector commands.

Setup guides:
- [Windows SDR# Local Detection](/C:/Users/mandi/Desktop/meteor_station/docs/sdrsharp_local_pipeline.md)
- [Ubuntu Local Audio Detection](/C:/Users/mandi/Desktop/meteor_station/docs/ubuntu_local_audio_pipeline.md)
- [LAN-Streamed RTL-SDR](/C:/Users/mandi/Desktop/meteor_station/docs/lan_streaming.md)

## Commands
- `meteor-station-sdrsharp-detect`: local audio detector for Windows VB-CABLE or Linux loopback/monitor inputs
- `meteor-station-pc-detect`: receiver that connects to an `rtl_tcp` IQ stream
- `meteor-station-pi-stream`: Pi-side `rtl_tcp` launcher

## Common Examples
### List local input devices

```bash
meteor-station-sdrsharp-detect --list-audio-devices
```

### Windows local live detection

```powershell
meteor-station-sdrsharp-detect `
  --config meteor_station.toml `
  --audio-input-profile sdrsharp_vb_cable `
  --runtime-profile local_sdrsharp `
  --detector-profile graves_sdrsharp_v4
```

### Ubuntu local live detection

```bash
meteor-station-sdrsharp-detect \
  --config meteor_station.toml \
  --audio-input-profile ubuntu_loopback \
  --runtime-profile ubuntu_local_audio \
  --detector-profile graves_sdrsharp_v4
```

### WAV replay

```bash
meteor-station-sdrsharp-detect \
  --config meteor_station.toml \
  --detector-profile graves_sdrsharp_v4 \
  --input-wav /path/to/fixture.wav
```

### LAN receiver

```bash
meteor-station-pc-detect \
  --config meteor_station.toml \
  --server-host 192.168.1.50 \
  --detector-profile graves_v4
```

## Useful Overrides
- `--detector-mode v4`: enable the stricter scorer without changing profile names
- `--output-dir PATH`: write logs and artifacts somewhere else
- `--no-wav`: disable review WAV output
- `--no-spectrogram`: disable candidate PNG spectrograms
- `--no-detection-waterfall`: disable rolling waterfall snapshots
- `--device-index N` or `--device-name TEXT`: override the configured local input device

## Output Files
By default the detector writes into `meteor_logs/`.

Core outputs:
- `events_v3.csv`: event log with the original columns plus appended review metrics
- `live_waterfall.png`: rolling waterfall snapshot
- `event_v3_*.png` / `event_v4_*.png`: candidate spectrograms
- `event_v3_*.wav` / `event_v4_*.wav`: candidate review audio
- `waterfalls/event_v3_*.png` / `waterfalls/event_v4_*.png`: candidate waterfall snapshots

Important CSV review columns:
- `event_type`
- `triggered_frames`
- `active_ratio`
- `longest_run_frames`
- `band_energy_ratio`
- `freq_jump_count`
- `score`
- `decision_reason`
- `detector_version`

## Review Guidance
- `v3` is the legacy detector path.
- `v4` is the stricter false-positive-reduction path.
- `meteor_candidate` should now be a smaller list than before, especially on noisy overnight runs.
- `impulse_rejected` and `broadband_rejected` usually indicate vertical waterfall streaks or wideband clicks.
- `weak_narrowband_rejected` indicates something looked tone-like but did not stay coherent long enough.

## Troubleshooting by Symptom
### No input device found
- Run `meteor-station-sdrsharp-detect --list-audio-devices`.
- On Windows, verify VB-CABLE is installed and visible.
- On Ubuntu, verify the monitor or loopback source exists with `pactl list short sources`.

### Wrong input device selected
- Prefer `device_index` once the correct device is stable.
- If indices drift, remove `device_index` and use `device_name_contains`.

### WAV replay fails immediately
- The WAV sample rate must match the configured sample rate, usually `48000 Hz`.

### No detections despite visible signal
- Confirm the demodulated audio tone lands in the configured detection band.
- For local audio paths, confirm the detector is attached to the source that actually carries demodulated USB audio.
- Compare the live source with a known-good WAV replay.

### Too many false positives
- Compare the same recording with `v3` and `v4`.
- Use a `*_v4` detector profile first before retuning thresholds.
- Inspect `band_energy_ratio`, `active_ratio`, and `decision_reason` in `events_v3.csv`.

### Dropped audio or callback warnings
- Increase `queue_max_blocks`.
- Reduce competing CPU load.
- Avoid heavy GUI tasks during continuous overnight runs.
