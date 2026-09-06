<#
.SYNOPSIS
    Windows wrapper for docker compose. Mirrors the Makefile commands.

.EXAMPLE
    .\scripts\dev.ps1 up
    .\scripts\dev.ps1 test
    .\scripts\dev.ps1 logs gateway
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'demo-up', 'demo-prepare', 'down', 'restart', 'logs', 'ps', 'build', 'test', 'lint', 'migrate',
        'gigaam-setup', 'voice-recovery-setup', 'voices', 'clean', 'help')]
    [string]$Command = 'help',

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path '.env')) {
    Write-Host '.env is missing; copying .env.example' -ForegroundColor Yellow
    Copy-Item '.env.example' '.env'
}

switch ($Command) {
    'up' { docker compose up --build @Rest }
    'demo-up' {
        docker compose --profile gigaam up --build -d --wait --wait-timeout 300 @Rest
    }
    'demo-prepare' {
        docker compose --profile gigaam run --rm --no-deps gigaam-worker python -m app.setup_models
        docker compose --profile gigaam up --build -d --wait --wait-timeout 300 @Rest
        docker compose exec gateway python -m app.scripts.render_voice_recovery
    }
    'down' { docker compose down @Rest }
    'restart' { docker compose down; docker compose up --build @Rest }
    'logs' { docker compose logs -f @Rest }
    'ps' { docker compose ps }
    'build' { docker compose build @Rest }
    'test' {
        docker compose exec gateway pytest -v @Rest
        docker compose exec speech-service pytest -v @Rest
        docker compose exec ai-service pytest -v @Rest
        docker compose exec frontend npm test
    }
    'lint' {
        docker compose exec gateway ruff check app tests
        docker compose exec speech-service ruff check app tests
        docker compose exec ai-service ruff check app tests
        docker compose exec scenario-service ruff check app
        docker compose exec frontend npm run lint
    }
    'migrate' { docker compose exec gateway alembic upgrade head }
    'gigaam-setup' {
        docker compose --profile gigaam run --rm --no-deps gigaam-worker python -m app.setup_models
    }
    'voice-recovery-setup' {
        docker compose exec gateway python -m app.scripts.render_voice_recovery
    }
    'voices' { docker compose exec speech-service python -m app.scripts.list_voices }
    'clean' {
        docker compose down -v
        Get-ChildItem -Path 'data' -Include '*.db', '*.db-wal', '*.db-shm' -File -Recurse |
            Remove-Item -Force
    }
    default {
        Write-Host @'
Usage: .\scripts\dev.ps1 <command>

  up            start the development stack
  demo-up       start the demo stack with GigaAM and wait until healthy
  demo-prepare  first run: GigaAM weights + stack + recovery audio
  down          stop the stack
  restart       restart the stack
  logs          follow logs (optional service name: logs gateway)
  ps            show container status
  build         rebuild images
  test          run pytest in services and vitest in frontend
  lint          run ruff and eslint
  migrate       apply migrations

  gigaam-setup          download and verify local STT weights
  voice-recovery-setup  render recovery lines (stack must be running)
  voices                list TTS voices for avatar voice_id

  clean         remove containers, volumes and local databases
'@
    }
}
