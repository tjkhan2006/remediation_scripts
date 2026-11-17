param(
    [Parameter(Mandatory=$true)][string]$SdkRoot,
    [Parameter(Mandatory=$true)][string]$Project,
    [string]$Configuration = 'Debug'
)
$ErrorActionPreference = 'Stop'
$projectPath = (Resolve-Path $Project).Path
if ([IO.Path]::GetExtension($projectPath) -ne '.vcxproj') { throw 'Pass the copied official BasicUI .vcxproj project.' }
$xml = Get-Content -LiteralPath $projectPath -Raw
foreach ($unit in @('TagLinkAudit.cpp','SignatureChecks.cpp')) {
    if ($xml -notmatch [regex]::Escape($unit)) { throw "Add $unit to the copied BasicUI project before building." }
}
$buildDir = Join-Path $PSScriptRoot 'build'
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (!(Test-Path -LiteralPath $vswhere)) { throw 'Install Visual Studio C++ build tools with MSBuild and a Windows SDK.' }
$msbuild = & $vswhere -latest -requires Microsoft.Component.MSBuild -find 'MSBuild\**\Bin\MSBuild.exe' | Select-Object -First 1
if (!$msbuild) { throw 'MSBuild not found.' }
& py -3 (Join-Path $PSScriptRoot 'verify_sdk.py') $SdkRoot --out (Join-Path $buildDir 'sdk-headers.json')
if ($LASTEXITCODE) { throw 'Required installed SDK declarations missing.' }
& $msbuild $projectPath /t:Rebuild "/p:Configuration=$Configuration" /p:Platform=x64 /v:normal "/bl:$(Join-Path $buildDir 'build.binlog')" "/flp:logfile=$(Join-Path $buildDir 'build.txt');verbosity=normal"
if ($LASTEXITCODE) { throw 'Build or exact signature checks failed. Preserve the log; do not bypass checks.' }
@{
    utc = [DateTime]::UtcNow.ToString('o')
    status = 'COMPILED_WITH_SIGNATURE_CHECKS_ACROBAT_EXECUTION_PENDING'
    project = $projectPath
    configuration = $Configuration
    platform = 'x64'
    msbuild = $msbuild
    source_hashes = @(Get-FileHash (Join-Path $PSScriptRoot '*.cpp') -Algorithm SHA256 | Select-Object Path, Hash)
} | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $buildDir 'build-result.json')
Write-Host 'Build succeeded. Identify and hash the produced .api; live Acrobat validation is still required.'
