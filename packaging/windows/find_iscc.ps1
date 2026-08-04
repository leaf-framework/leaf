# Finds Inno Setup's ISCC.exe compiler, printing its full path to stdout.
# Set an ISCC_PATH project/group CI/CD variable to override if it's
# installed somewhere none of these check.
$candidates = @(
    $env:ISCC_PATH,
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 7\ISCC.exe",
    "C:\Program Files\Inno Setup 7\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) }

# Where-Object unwraps a single match to a bare string, not a 1-element
# array -- indexing that with [0] silently returns just its first
# CHARACTER ('C'), not the path. @(...) forces array context first so
# [0] always means "first element" regardless of match count.
$isccPath = @($candidates)[0]
if (-not $isccPath) {
    Write-Error "ISCC.exe not found. Checked ISCC_PATH and Inno Setup 6/7 default install locations. Set an ISCC_PATH CI/CD variable if it's installed elsewhere."
    exit 1
}
Write-Output $isccPath
