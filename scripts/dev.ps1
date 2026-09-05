<#
.SYNOPSIS
    Обёртка над docker compose для Windows — то же, что Makefile, но без make.

.EXAMPLE
    .\scripts\dev.ps1 up
    .\scripts\dev.ps1 test
    .\scripts\dev.ps1 logs gateway
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'down', 'restart', 'logs', 'ps', 'build', 'test', 'lint', 'migrate',
        'gigaam-setup', 'voice-recovery-setup', 'voices', 'clean', 'help')]
    [string]$Command = 'help',

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path '.env')) {
    Write-Host 'Файла .env нет — копирую из .env.example' -ForegroundColor Yellow
    Copy-Item '.env.example' '.env'
}

switch ($Command) {
    'up' { docker compose up --build @Rest }
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
Использование: .\scripts\dev.ps1 <команда>

  up        поднять всё (dev-режим)
  down      остановить
  restart   перезапустить
  logs      логи (можно указать сервис: logs gateway)
  ps        состояние контейнеров
  build     пересобрать образы
  test      pytest в сервисах + vitest во фронтенде
  lint      ruff + eslint
  migrate   применить миграции

  gigaam-setup          скачать и сверить веса локального STT (до демо)
  voice-recovery-setup  озвучить реплики «повторите» (стек должен быть поднят)
  voices                список голосов TTS — для voice_id нового аватара

  clean     убрать контейнеры, тома и локальные БД
'@
    }
}
