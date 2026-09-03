.DEFAULT_GOAL := help
COMPOSE := docker compose

.PHONY: help up down restart logs ps build test lint fmt migrate revision contracts clean

help: ## Список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up: ## Поднять всё (dev-режим)
	$(COMPOSE) up --build

down: ## Остановить и убрать контейнеры
	$(COMPOSE) down

restart: down up ## Перезапустить

logs: ## Логи всех сервисов
	$(COMPOSE) logs -f

ps: ## Состояние контейнеров
	$(COMPOSE) ps

build: ## Пересобрать образы
	$(COMPOSE) build

test: ## Тесты gateway (инварианты отмены и автомата этапов)
	$(COMPOSE) exec gateway pytest -v

lint: ## ruff по сервисам + eslint во фронтенде
	$(COMPOSE) exec gateway ruff check app tests
	$(COMPOSE) exec speech-service ruff check app
	$(COMPOSE) exec ai-service ruff check app
	$(COMPOSE) exec scenario-service ruff check app
	$(COMPOSE) exec frontend npm run lint

fmt: ## Форматирование
	$(COMPOSE) exec gateway ruff format app tests
	$(COMPOSE) exec speech-service ruff format app
	$(COMPOSE) exec ai-service ruff format app
	$(COMPOSE) exec scenario-service ruff format app

migrate: ## Применить миграции
	$(COMPOSE) exec gateway alembic upgrade head

revision: ## Создать ревизию: make revision M="описание"
	$(COMPOSE) exec gateway alembic revision --autogenerate -m "$(M)"

contracts: ## Сгенерировать JSON Schema контрактов для фронтенда
	$(COMPOSE) exec gateway python -m ath_contracts.export_schema \
		--out /app/contracts-schema.json
	$(COMPOSE) cp gateway:/app/contracts-schema.json \
		./services/frontend/src/contracts/schema.json

clean: ## Убрать контейнеры, тома и локальные данные (БД будет стёрта)
	$(COMPOSE) down -v
	rm -f data/*.db data/*.db-wal data/*.db-shm
