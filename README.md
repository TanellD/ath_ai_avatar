# Цифровой тренажёр корпоративных тренировок

Веб-приложение, в котором сотрудник проходит тренировочный диалог с говорящим
персонажем по заданному сценарию. Методист получает историю разговора и
итоговую оценку с цитатой под каждым баллом.

Постановка целиком — [Claude.md](Claude.md). Читать перед любой задачей по коду.

> **Текущая фаза: текстовый ввод.** Claude.md описывает голосовой ввод как
> основной; STT, микрофон и VAD пока существуют только как определения
> интерфейсов. Что именно сокращено и как это включить —
> [docs/stt-phase.md](docs/stt-phase.md).

## Запуск

Нужен только Docker с плагином Compose (v2.24+).

```bash
cp .env.example .env
docker compose up --build
```

Ключи API не требуются: `TTS_PROVIDER` и `LLM_PROVIDER` по умолчанию `mock`.
Всё поднимается, отвечает на `/health`, WebSocket подключается.

| Что | Адрес |
|---|---|
| Приложение (vite dev) | http://localhost:5173 |
| Gateway, OpenAPI | http://localhost:8000/docs |
| Speech-service | http://localhost:8010/docs |
| AI-service | http://localhost:8030/docs |
| Scenario-service | http://localhost:8050/docs |

Прод-сборка (nginx вместо vite, без bind-mount исходников):

```bash
docker compose -f docker-compose.yml up --build
```

### Проверка, что всё живо

```bash
curl localhost:8000/ready     # gateway + все зависимости
curl localhost:8050/scenarios # засеянные шаблоны сценариев
```

### С реальными моделями

В `.env`:

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

`TTS_PROVIDER=elevenlabs|yandex` требует реализации провайдера — сейчас там
заглушки с описанием, что нужно сделать (`services/speech-service/app/tts/`).

## Структура

```
packages/contracts/     общие контракты данных (Claude.md §7) — источник истины
services/
  gateway/              оркестратор: gen_id, автомат этапов, WebSocket сессии
  speech-service/       TTS. Пространство STT объявлено без реализации
  ai-service/           реплики персонажа, классификация, итоговая оценка
  scenario-service/     сценарии, шаблоны, рубрики методиста
  frontend/             React + Vite
data/                   SQLite-файлы (bind-mount, в git не попадают)
docs/                   архитектура, контракты, бюджет задержки, план STT
tatarby-main/           референсный проект, только для чтения
```

## Разработка

```bash
make up          # docker compose up --build
make logs        # логи всех сервисов
make test        # pytest в gateway
make lint        # ruff по сервисам + eslint во фронтенде
make down
```

Без make (Windows): `.\scripts\dev.ps1 up`, `.\scripts\dev.ps1 test` и так далее.

Dev-режим включён по умолчанию (`docker-compose.override.yml`): исходники
прокинуты внутрь контейнеров, uvicorn и vite перезапускаются на правку.

### Три вещи, которые ломать нельзя

Читаются за пять минут и стоят того — на них держится приёмка.

1. **`gen_id` и отмена** — `services/gateway/app/orchestrator/generation.py`.
   Метрика 4 (возвраты отменённого хвоста = 0) — жёсткий инвариант, не цель.
2. **Часы системы — воспроизводимое аудио** —
   `services/frontend/src/audio/PlaybackClock.ts`. Никаких `setInterval`;
   ESLint это проверяет.
3. **Переход между этапами делает код, а не модель** —
   `services/gateway/app/orchestrator/fsm.py`. LLM только классифицирует.

Бюджеты и способ их измерения — [docs/latency-budget.md](docs/latency-budget.md).

### Миграции

Схема сейчас создаётся автоматически при старте сервиса — этого хватает для
скелета. Первая ревизия alembic снимается один раз, из работающего контейнера:

```bash
docker compose exec gateway alembic revision --autogenerate -m "initial schema"
docker compose exec gateway alembic upgrade head
```

После этого автосоздание таблиц надо убрать (`app/db/engine.py`), чтобы способ
создания схемы остался один. Подробности — `services/gateway/app/alembic/README.md`.

### Переезд на Postgres

Раскомментировать блок `postgres` в `docker-compose.yml` и заменить две
переменные в `.env`. Код не меняется: обращения к БД идут через репозитории.
