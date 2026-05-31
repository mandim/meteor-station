param(
    [string]$Config = "meteor_station.toml",
    [string]$DetectorProfile = "graves",
    [string]$ServerHost = "192.168.1.50",
    [int]$ServerPort = 1234,
    [int]$CenterFreqHz = 143048400,
    [int]$VfoHz = 143048400,
    [int]$UsbBandwidthHz = 3000,
    [int]$IqSampleRate = 240000,
    [int]$AudioSampleRate = 48000,
    [string]$OutputDir = "meteor_logs",
    [switch]$SaveWav,
    [switch]$NoWav,
    [switch]$NoSpectrogram,
    [switch]$NoDetectionWaterfall,
    [switch]$ListenAudio,
    [switch]$ShowWaterfall,
    [Nullable[int]]$AudioOutputDevice = $null,
    [string]$WaterfallPath = "",
    [double]$WaterfallWindowSeconds = 30,
    [double]$WaterfallUpdateSeconds = 5,
    [double]$WaterfallMinHz = 0,
    [double]$WaterfallMaxHz = 4000
)

$ErrorActionPreference = "Stop"

function Get-MeteorPython {
    $candidates = @()

    if ($env:METEOR_PYTHON) {
        $candidates += $env:METEOR_PYTHON
    }

    if ($env:CONDA_PREFIX) {
        $candidates += (Join-Path $env:CONDA_PREFIX "python.exe")
    }

    $homeDir = [Environment]::GetFolderPath("UserProfile")

    $candidates += @(
        (Join-Path $homeDir "anaconda3\envs\meteor\python.exe"),
        (Join-Path $homeDir "miniconda3\envs\meteor\python.exe"),
        "C:\ProgramData\anaconda3\envs\meteor\python.exe",
        "C:\ProgramData\miniconda3\envs\meteor\python.exe"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }

    throw @"
Could not find the 'meteor' environment Python.

Tried:
- `$env:METEOR_PYTHON
- `$env:CONDA_PREFIX\python.exe
- %USERPROFILE%\anaconda3\envs\meteor\python.exe
- %USERPROFILE%\miniconda3\envs\meteor\python.exe
- C:\ProgramData\anaconda3\envs\meteor\python.exe
- C:\ProgramData\miniconda3\envs\meteor\python.exe

Set METEOR_PYTHON to the exact python.exe path if your install is elsewhere.
"@
}

$python = Get-MeteorPython
$scriptPath = Join-Path $PSScriptRoot "src\meteor_station\cli\pc_detect.py"

if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Script not found: $scriptPath"
}

$scriptArgs = @(
    "--config", $Config,
    "--detector-profile", $DetectorProfile,
    "--server-host", $ServerHost,
    "--server-port", $ServerPort,
    "--center-freq-hz", $CenterFreqHz,
    "--vfo-hz", $VfoHz,
    "--usb-bandwidth-hz", $UsbBandwidthHz,
    "--iq-sample-rate", $IqSampleRate,
    "--audio-sample-rate", $AudioSampleRate,
    "--output-dir", $OutputDir
)

if ($SaveWav) {
    $scriptArgs += "--save-wav"
}

if ($NoWav) {
    $scriptArgs += "--no-wav"
}

if ($NoSpectrogram) {
    $scriptArgs += "--no-spectrogram"
}

if ($NoDetectionWaterfall) {
    $scriptArgs += "--no-detection-waterfall"
}

$scriptArgs += @(
    "--waterfall-window-seconds", $WaterfallWindowSeconds,
    "--waterfall-update-seconds", $WaterfallUpdateSeconds,
    "--waterfall-min-hz", $WaterfallMinHz,
    "--waterfall-max-hz", $WaterfallMaxHz
)

if ($ListenAudio) {
    $scriptArgs += "--listen-audio"
}

if ($ShowWaterfall) {
    $scriptArgs += "--show-waterfall"
}

if ($null -ne $AudioOutputDevice) {
    $scriptArgs += @("--audio-output-device", $AudioOutputDevice)
}

if ($WaterfallPath) {
    $scriptArgs += @("--waterfall-path", $WaterfallPath)
}

Write-Host "Using Python: $python"
Write-Host "Running script: $scriptPath"
Write-Host "Server: $ServerHost`:$ServerPort"
Write-Host "Detector profile: $DetectorProfile"

& $python $scriptPath @scriptArgs
