param(
    [string]$Script = "meteor_detector_v3.py",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
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
$scriptPath = Join-Path $PSScriptRoot $Script

if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Script not found: $scriptPath"
}

Write-Host "Using Python: $python"
Write-Host "Running script: $scriptPath"

& $python $scriptPath @ScriptArgs
