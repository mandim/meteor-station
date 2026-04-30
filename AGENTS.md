# Meteor Station

This repository is a meteor-detection prototype that is moving toward a headless Raspberry Pi deployment.

Current repo state:
- `meteor_detector.py` is the first-pass detector using audio FFT peak detection and spectrogram export.
- `meteor_detector_v2.py` adds steady-tone rejection, event classification, and optional WAV export.
- `meteor_detector_v3.py` adds tighter band detection, peak-prominence checks, and broadband rejection.
- `meteor_detector_v3_tuned_from_sdrsharp.py` captures the currently tuned SDR# assumptions around the GRAVES setup.
- `audio_test.py` is a basic input-level sanity check.
- `meteor_logs/` contains sample detector output.
- `Yaggi holders/` contains antenna-holder CAD assets and is not part of the Python runtime.

Project goal:
- Turn the current Windows-oriented detector scripts into a Raspberry Pi meteor station that can run unattended, log detections reliably, and be maintained as a real software project rather than a collection of one-off scripts.

Working rules for this repo:
- Preserve the current tuned detector behavior unless there is a clear reason to change it.
- Prefer introducing new modules and config files over repeatedly forking detector scripts.
- Treat hardware-specific values such as audio device IDs, SDR center frequency assumptions, and output paths as configuration, not hardcoded constants.
- Prefer Raspberry Pi compatible choices: headless operation, no desktop dependencies, and libraries that work on ARM Linux.
- Do not assume SDR# or VB-CABLE will exist on the Raspberry Pi. Any Pi-targeted work should support ALSA audio input, prerecorded WAV fixtures, or SDR pipelines such as `rtl_fm`.
- Keep offline validation practical. When possible, make detector logic testable against saved audio fixtures instead of requiring live radio hardware.
- Keep output structured and durable: event logs, spectrograms, optional WAV captures, and future service logs should land in predictable directories.

When extending the project:
- Favor a package layout such as `src/meteor_station/` with a CLI entrypoint instead of adding more top-level scripts.
- Separate detection logic, input capture, event persistence, and visualization/export concerns.
- Prefer `matplotlib` only for saved artifacts, not any interactive UI workflow.
- Design for eventual `systemd` service operation on Raspberry Pi OS.

Validation expectations:
- For logic changes, add or update fixture-based tests if possible.
- For live-capture changes, document the expected input path and how to run a manual verification pass.
