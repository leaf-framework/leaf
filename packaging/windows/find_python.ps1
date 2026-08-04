# Finds a python.exe on this machine whose OWN process architecture
# matches -Arch (AMD64 or ARM64), printing its full path to stdout.
#
# Why this exists (not just `python` on PATH): PyInstaller can't
# cross-compile -- it always freezes for whichever python.exe actually
# invokes it. This project's Windows runner is ARM64 hardware (Windows-on-
# ARM under UTM on Apple Silicon), and both amd64 and arm64 Python builds
# can be installed side by side there, so bare `python` on PATH isn't
# reliable enough to pick the right one for a given target.
#
# Deliberately NOT platform.machine(): confirmed directly on this
# project's runner that it always reports the underlying hardware's
# native architecture (ARM64), regardless of which python.exe actually
# runs it -- including for a verified, genuine amd64 python.org build.
# PROCESSOR_ARCHITECTURE (read from *within* the candidate's own process)
# correctly reflects that process's own architecture instead, respecting
# x64-under-ARM64 emulation.
#
# Searched under C:\Users\*, not just $env:LOCALAPPDATA: if gitlab-runner
# runs as a Windows service, it very likely runs under a different
# account than whichever interactive user installed Python, so
# $env:LOCALAPPDATA in the job's context resolves to that service
# account's (probably empty) profile, not the one Python actually lives
# under -- searching every user's profile directly sidesteps needing to
# know or fix which account the service runs as.
#
# Two different install layouts are checked: the classic python.org
# installer (AppData\Local\Programs\Python\PythonXYZ\) and the newer
# "Python Install Manager" layout used by Python 3.13+
# (AppData\Local\Python\pythoncore-X.Y-64\).
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("amd64", "arm64")]
    [string]$Arch
)

$targetMachine = $Arch.ToUpper()

$candidates = @("python", "C:\Python312\python.exe", "C:\Python313\python.exe")
$candidates += Get-ChildItem -Path "C:\Users\*\AppData\Local\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }
$candidates += Get-ChildItem -Path "C:\Users\*\AppData\Local\Python\pythoncore-*-64\python.exe" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }
$candidates += Get-ChildItem -Path "C:\Users\*\AppData\Local\Python\pythoncore-*-arm64\python.exe" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }

foreach ($candidate in $candidates) {
    $exe = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $exe) { continue }
    $machine = & $exe.Source -c "import os; print(os.environ.get('PROCESSOR_ARCHITECTURE'))" 2>$null
    if ($machine -eq $targetMachine) {
        Write-Output $exe.Source
        exit 0
    }
}

Write-Error "No $targetMachine python.exe found (checked PATH and common python.org install locations). Install the matching python.org installer for $Arch on this runner."
exit 1
