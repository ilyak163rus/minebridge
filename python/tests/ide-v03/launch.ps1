param([string]$Interpreter)

$ErrorActionPreference = 'Stop'
$ideV03Root = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$ideV03Code = Join-Path $ideV03Root '.tools/vscode-t10/app/Code.exe'
$ideV03Helper = Join-Path $PSScriptRoot 'run.js'
if (-not $Interpreter) { $Interpreter = Join-Path $ideV03Root '.venv-v03-314/Scripts/python.exe' }
$Interpreter = (Resolve-Path -LiteralPath $Interpreter).Path
$ideV03Work = Join-Path $ideV03Root '.work'

$env:ELECTRON_RUN_AS_NODE = '1'
try {
    $ideV03Prepare = Start-Process -FilePath $ideV03Code -ArgumentList @(
        ('"' + $ideV03Helper + '"'), '--prepare', ('"' + $Interpreter + '"')
    ) -WindowStyle Hidden -PassThru -Wait `
        -RedirectStandardOutput (Join-Path $ideV03Work 'ide-v03-prepare-stdout.log') `
        -RedirectStandardError (Join-Path $ideV03Work 'ide-v03-prepare-stderr.log')
    if ($ideV03Prepare.ExitCode -ne 0) { throw 'IDE v03 preparation failed' }
} finally { Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue }
Remove-Item Env:VSCODE_IPC_HOOK_CLI -ErrorAction SilentlyContinue

$ideV03Arguments = @(
    ('--extensionDevelopmentPath="' + $PSScriptRoot + '"')
    ('--extensionTestsPath="' + $ideV03Helper + '"')
    ('--user-data-dir="' + (Join-Path $ideV03Work 'ide-v03-user-data') + '"')
    ('--extensions-dir="' + (Join-Path $env:USERPROFILE '.vscode/extensions') + '"')
    '--disable-workspace-trust'
    '--skip-welcome'
    '--skip-release-notes'
    '--new-window'
    ('"' + (Join-Path $ideV03Work 'ide-v03-workspace') + '"')
)
$ideV03Process = Start-Process -FilePath $ideV03Code -ArgumentList $ideV03Arguments `
    -WindowStyle Hidden -PassThru -Wait `
    -RedirectStandardOutput (Join-Path $ideV03Work 'ide-v03-stdout.log') `
    -RedirectStandardError (Join-Path $ideV03Work 'ide-v03-stderr.log')
$ideV03Result = Get-Content (Join-Path $ideV03Work 'ide-v03-results.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($ideV03Process.ExitCode -ne 0 -or $ideV03Result.status -ne 'passed') {
    throw ('IDE v03 check failed; inspect .work/ide-v03-results.json: ' + $ideV03Result.error)
}
& $Interpreter -I (Join-Path $PSScriptRoot 'verify_artifact.py')
if ($LASTEXITCODE -ne 0) { throw 'IDE final-wheel byte verification failed' }
Write-Output ('IDE v03 passed: VS Code ' + $ideV03Result.vscode)
