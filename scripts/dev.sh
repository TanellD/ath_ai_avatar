#!/usr/bin/env bash
# Обёртка над docker compose — то же, что Makefile, для систем без make.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "Файла .env нет — копирую из .env.example"
    cp .env.example .env
fi

command="${1:-help}"
shift || true

case "$command" in
    up)      docker compose up --build "$@" ;;
    down)    docker compose down "$@" ;;
    restart) docker compose down && docker compose up --build "$@" ;;
    logs)    docker compose logs -f "$@" ;;
    ps)      docker compose ps ;;
    build)   docker compose build "$@" ;;
    test)    docker compose exec gateway pytest -v "$@" ;;
    lint)
        docker compose exec gateway ruff check app tests
        docker compose exec speech-service ruff check app
        docker compose exec ai-service ruff check app
        docker compose exec scenario-service ruff check app
        docker compose exec frontend npm run lint
        ;;
    migrate) docker compose exec gateway alembic upgrade head ;;
    clean)
        docker compose down -v
        rm -f data/*.db data/*.db-wal data/*.db-shm
        ;;
    *)
        cat <<'EOF'
Использование: ./scripts/dev.sh <команда>

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
EOF
        ;;
esac
