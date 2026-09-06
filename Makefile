.DEFAULT_GOAL := help
COMPOSE := docker compose

.PHONY: help up demo-up demo-prepare down restart logs ps build test lint fmt migrate revision contracts clean gigaam-setup voice-recovery-setup voices

help: ## Список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up: ## Поднять всё (dev-режим)
	$(COMPOSE) up --build

demo-up: ## Поднять готовый к демонстрации стек с GigaAM и дождаться healthcheck
	$(COMPOSE) --profile gigaam up --build -d --wait --wait-timeout 300

demo-prepare: gigaam-setup demo-up ## Первый запуск: подготовить GigaAM, поднять стек и предрендерить recovery-аудио
	$(COMPOSE) exec gateway python -m app.scripts.render_voice_recovery

down: ## Остановить и убрать контейнеры
	$(COMPOSE) down

restart: down up ## Перезапустить

logs: ## Логи всех сервисов
	$(COMPOSE) logs -f

ps: ## Состояние контейнеров
	$(COMPOSE) ps

build: ## Пересобрать образы
	$(COMPOSE) build

test: ## Тесты gateway, speech-service, ai-service и фронтенда (инварианты)
	$(COMPOSE) exec gateway pytest -v
	$(COMPOSE) exec speech-service pytest -v
	$(COMPOSE) exec ai-service pytest -v
	$(COMPOSE) exec frontend npm test

lint: ## ruff по сервисам + eslint во фронтенде
	$(COMPOSE) exec gateway ruff check app tests
	$(COMPOSE) exec speech-service ruff check app tests
	$(COMPOSE) exec ai-service ruff check app tests
	$(COMPOSE) exec scenario-service ruff check app
	$(COMPOSE) exec frontend npm run lint

fmt: ## Форматирование
	$(COMPOSE) exec gateway ruff format app tests
	$(COMPOSE) exec speech-service ruff format app tests
	$(COMPOSE) exec ai-service ruff format app tests
	$(COMPOSE) exec scenario-service ruff format app

gigaam-setup: ## Скачать и сверить веса GigaAM заранее (до демо; старт worker'а офлайновый)
	$(COMPOSE) --profile gigaam run --rm --no-deps gigaam-worker \
		python -m app.setup_models

voice-recovery-setup: ## Озвучить реплики «повторите, пожалуйста» заранее (стек должен быть поднят)
	$(COMPOSE) exec gateway python -m app.scripts.render_voice_recovery

voices: ## Показать голоса TTS-провайдера (для voice_id в реестре аватаров)
	$(COMPOSE) exec speech-service python -m app.scripts.list_voices

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
