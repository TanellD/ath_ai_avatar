<#
.SYNOPSIS
    Экспортирует JSON Schema общих контрактов для фронтенда.

.DESCRIPTION
    services/frontend/src/contracts/events.ts пока написан руками. Этот скрипт
    выгружает схему из packages/contracts, чтобы типы можно было сверить или
    сгенерировать (json-schema-to-typescript и подобные).

    Рассинхрон питоновского контракта и TS-зеркала ломает фильтрацию по gen_id
    молча: событие просто не распознаётся и отбрасывается.
#>

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$out = 'services/frontend/src/contracts/schema.json'

Write-Host "Экспорт схемы в $out" -ForegroundColor Cyan

docker compose exec -T gateway python -m ath_contracts.export_schema --out /tmp/schema.json
docker compose cp gateway:/tmp/schema.json $out

Write-Host 'Готово. Сверьте events.ts со схемой либо сгенерируйте типы:' -ForegroundColor Green
Write-Host '  npx json-schema-to-typescript ' -NoNewline
Write-Host $out -NoNewline
Write-Host ' -o services/frontend/src/contracts/generated.d.ts'
