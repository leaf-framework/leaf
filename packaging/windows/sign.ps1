# Signs files with UNLOCK's Azure Artifact Signing certificate
# (account euw-sign-unlock-p, profile unlock-public-trust).
#
# In CI the job's GitLab ID token ($env:AZURE_ID_TOKEN) is exchanged for the
# managed identity named by AZURE_CLIENT_ID; no secret is stored anywhere.
# Locally, an `az login` with an account holding the signer role works too.
#
# signtool, the signing library and the .NET runtime it needs are fetched on
# first use into build\signing, pinned and hash-checked. All x64: the library
# has no ARM64 build, and x64 runs fine under emulation on the ARM64 runner.
param(
    [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)]
    [string[]]$Files
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$downloads = @(
    @{
        Name = "signtool"
        Url = "https://api.nuget.org/v3-flatcontainer/microsoft.windows.sdk.buildtools/10.0.28000.2705/microsoft.windows.sdk.buildtools.10.0.28000.2705.nupkg"
        Sha256 = "8bfdfb6ca2633f531cf80b5fa22512ba61a394d7988f0970db83baadc67929ed"
    },
    @{
        Name = "dlib"
        Url = "https://api.nuget.org/v3-flatcontainer/microsoft.artifactsigning.client/1.0.128/microsoft.artifactsigning.client.1.0.128.nupkg"
        Sha256 = "74bd7d27e6ce1051409c38d9b46bc8df0400ecd643d51ffbf2ac00869061e40b"
    },
    @{
        Name = "dotnet"
        Url = "https://builds.dotnet.microsoft.com/dotnet/Runtime/8.0.31/dotnet-runtime-8.0.31-win-x64.zip"
        Sha256 = "7deabbefdc83e378b343c551fe447b86002680eea91355b1f6f81d0c9ab0dcaa"
    }
)

$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\build\signing"))
$signtool = Join-Path $root "signtool\bin\10.0.28000.0\x64\signtool.exe"
$dlib = Join-Path $root "dlib\bin\x64\Azure.CodeSigning.Dlib.dll"
$metadata = Join-Path $root "metadata.json"

if (-not (Test-Path (Join-Path $root "ready"))) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    foreach ($d in $downloads) {
        $archive = Join-Path $root "$($d.Name).zip"
        $target = Join-Path $root $d.Name
        Invoke-WebRequest -UseBasicParsing -Uri $d.Url -OutFile $archive
        $hash = (Get-FileHash -Algorithm SHA256 $archive).Hash.ToLower()
        if ($hash -ne $d.Sha256) {
            throw "Checksum mismatch for $($d.Url): got $hash"
        }
        if (Test-Path $target) {
            Remove-Item -Recurse -Force $target
        }
        [System.IO.Compression.ZipFile]::ExtractToDirectory($archive, $target)
        Remove-Item $archive
    }
    # Excluding the browser login makes an expired session fail once instead
    # of opening a login window per file.
    @{
        Endpoint = "https://weu.codesigning.azure.net/"
        CodeSigningAccountName = "euw-sign-unlock-p"
        CertificateProfileName = "unlock-public-trust"
        ExcludeCredentials = @("InteractiveBrowserCredential")
    } | ConvertTo-Json | Set-Content -Path $metadata -Encoding ascii
    New-Item -ItemType File -Path (Join-Path $root "ready") | Out-Null
}

# The library is .NET; point it at the unpacked runtime, not a system install.
$env:DOTNET_ROOT = Join-Path $root "dotnet"
$env:DOTNET_ROOT_X64 = $env:DOTNET_ROOT

# Azure.Identity reads the federated token from a file, not a variable.
$tokenFile = $null
if ($env:AZURE_ID_TOKEN -and -not $env:AZURE_FEDERATED_TOKEN_FILE) {
    $tokenFile = Join-Path $root "id-token.txt"
    Set-Content -Path $tokenFile -Value $env:AZURE_ID_TOKEN -NoNewline -Encoding ascii
    $env:AZURE_FEDERATED_TOKEN_FILE = $tokenFile
}

try {
    # /tr is required: the certificate lives only days, the timestamp keeps
    # the signature valid long after.
    & $signtool sign /v /fd SHA256 /tr http://timestamp.acs.microsoft.com /td SHA256 /dlib $dlib /dmdf $metadata @Files
    $code = $LASTEXITCODE
}
finally {
    # Unset too: when called with `&` the variable outlives this script and
    # would point the next call at a deleted file.
    if ($tokenFile) {
        Remove-Item -Force $tokenFile
        Remove-Item Env:AZURE_FEDERATED_TOKEN_FILE
    }
}
exit $code
