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
    [ValidateSet('up', 'down', 'restart', 'logs', 'ps', 'build', 'test', 'lint', 'migrate', 'clean', 'help')]
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
    }
    'lint' {
        docker compose exec gateway ruff check app tests
        docker compose exec speech-service ruff check app tests
        docker compose exec ai-service ruff check app tests
        docker compose exec scenario-service ruff check app
        docker compose exec frontend npm run lint
    }
    'migrate' { docker compose exec gateway alembic upgrade head }
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
  test      тесты gateway
  lint      ruff + eslint
  migrate   применить миграции
  clean     убрать контейнеры, тома и локальные БД
'@
    }
}
