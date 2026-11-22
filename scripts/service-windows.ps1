[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('init', 'start', 'check')]
    [string]$Action = 'start',
    [Alias('external-db')]
    [switch]$ExternalDb
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Install uv and reopen PowerShell before running this script.'
}
if ($ExternalDb -and $Action -eq 'check') {
    throw '-ExternalDb applies only to init/start.'
}

$arguments = @(
    'run', '--locked', '--inexact', '--project', (Join-Path $projectRoot 'backend'),
    'python', (Join-Path $PSScriptRoot 'service_manager.py'), $Action
)
if ($ExternalDb) {
    $arguments += '--external-db'
}
& uv @arguments
exit $LASTEXITCODE
