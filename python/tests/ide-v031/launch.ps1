param([string]$Interpreter, [string]$Wheel)

$ErrorActionPreference = 'Stop'
$ideV031Root = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$ideV031Code = Join-Path $ideV031Root '.tools/vscode-t10/app/Code.exe'
$ideV031Helper = Join-Path $PSScriptRoot 'run.js'
if (-not $Interpreter) { $Interpreter = Join-Path $ideV031Root '.venv-v031-314/Scripts/python.exe' }
if (-not $Wheel) { $Wheel = Join-Path $ideV031Root 'dist/v0.3.1/minebridge-0.3.1-py3-none-any.whl' }
$Interpreter = (Resolve-Path -LiteralPath $Interpreter).Path
$Wheel = (Resolve-Path -LiteralPath $Wheel).Path
$ideV031Work = Join-Path $ideV031Root '.work'

$env:ELECTRON_RUN_AS_NODE = '1'
try {
    $ideV031Prepare = Start-Process -FilePath $ideV031Code -ArgumentList @(
        ('"' + $ideV031Helper + '"'), '--prepare', ('"' + $Interpreter + '"'), ('"' + $Wheel + '"')
    ) -WindowStyle Hidden -PassThru -Wait `
        -RedirectStandardOutput (Join-Path $ideV031Work 'ide-v031-prepare-stdout.log') `
        -RedirectStandardError (Join-Path $ideV031Work 'ide-v031-prepare-stderr.log')
    if ($ideV031Prepare.ExitCode -ne 0) { throw 'IDE 0.3.1 preparation failed' }
} finally { Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue }
Remove-Item Env:VSCODE_IPC_HOOK_CLI -ErrorAction SilentlyContinue

$ideV031Arguments = @(
    ('--extensionDevelopmentPath="' + $PSScriptRoot + '"')
    ('--extensionTestsPath="' + $ideV031Helper + '"')
    ('--user-data-dir="' + (Join-Path $ideV031Work 'ide-v031-user-data') + '"')
    ('--extensions-dir="' + (Join-Path $env:USERPROFILE '.vscode/extensions') + '"')
    '--disable-workspace-trust'
    '--skip-welcome'
    '--skip-release-notes'
    '--new-window'
    ('"' + (Join-Path $ideV031Work 'ide-v031-workspace') + '"')
)
$ideV031Process = Start-Process -FilePath $ideV031Code -ArgumentList $ideV031Arguments `
    -WindowStyle Hidden -PassThru -Wait `
    -RedirectStandardOutput (Join-Path $ideV031Work 'ide-v031-stdout.log') `
    -RedirectStandardError (Join-Path $ideV031Work 'ide-v031-stderr.log')
$ideV031Result = Get-Content (Join-Path $ideV031Work 'ide-v031-results.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($ideV031Process.ExitCode -ne 0 -or $ideV031Result.status -ne 'passed') {
    throw ('IDE 0.3.1 check failed: ' + $ideV031Result.error)
}
& $Interpreter -I (Join-Path $PSScriptRoot 'verify_artifact.py')
if ($LASTEXITCODE -ne 0) { throw 'IDE final-wheel byte verification failed' }
Write-Output ('IDE 0.3.1 passed: VS Code ' + $ideV031Result.vscode)
