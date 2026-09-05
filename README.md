# Цифровой тренажёр корпоративных тренировок

Веб-приложение, в котором сотрудник проходит тренировочный диалог с говорящим
персонажем по заданному сценарию. Методист получает историю разговора и
итоговую оценку с цитатой под каждым баллом.

Актуальная архитектура — [docs/architecture.md](docs/architecture.md), план
голосового ввода — [docs/voice-input-plan.md](docs/voice-input-plan.md).

Текстовый ввод работает как прежде. Первый голосовой режим — push-to-talk с
Soniox STT; GigaAM failover и hands-free добавляются следующими фазами.

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

LLM — Anthropic (реализован) или OpenAI-совместимый прокси/VseLLM
(реализован, второй вариант — по итогам ветки `poc`):

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# либо
LLM_PROVIDER=openai_compatible
OPENAI_COMPATIBLE_BASE_URL=https://api.vsellm.ru/v1
OPENAI_COMPATIBLE_API_KEY=...
LLM_FAST_MODEL=google/gemini-2.5-flash    # имя модели ЭТОГО прокси
LLM_STRONG_MODEL=google/gemini-2.5-flash
```

TTS — Soniox (реализован, тот же провайдер, что подтвердила ветка `poc`,
голос "Nina"):

```dotenv
TTS_PROVIDER=soniox
SONIOX_API_KEY=...
STT_PROVIDER=soniox
```

`TTS_PROVIDER=elevenlabs|yandex` остаются заглушками — описание, что нужно
сделать, в `services/speech-service/app/tts/`.

### Без Docker (быстрый цикл при разработке)

Каждый Python-сервис — отдельный устанавливаемый пакет со своим venv:

```bash
cd services/gateway            # или speech-service / ai-service / scenario-service
python -m venv .venv
.venv/Scripts/activate         # Linux/macOS: source .venv/bin/activate
pip install -e ../../packages/contracts
pip install -e ".[dev]"

pytest -v                      # инварианты — без сети и без Docker
ruff check app tests
uvicorn app.main:app --reload --port 8000   # порт свой у каждого сервиса
```

Фронтенд — обычный Vite-проект:

```bash
cd services/frontend
npm install
npm run typecheck
npm run lint
npm run dev                    # смотрит на localhost:8000 и :8050 по умолчанию
```

`docker compose up` — по-прежнему единственная проверка, которая гоняет все
пять сервисов вместе через реальную сеть контейнеров; локальный цикл ловит
логические ошибки быстрее, но не заменяет его перед демо.

## Структура

```
packages/contracts/     общие контракты данных (Claude.md §7) — источник истины
services/
  gateway/              оркестратор: gen_id, автомат этапов, WebSocket сессии
  speech-service/       потоковые TTS и STT
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
make test        # pytest в сервисах + vitest во фронтенде
make lint        # ruff по сервисам + eslint во фронтенде
make down

make gigaam-setup          # скачать и сверить веса локального STT (до демо)
make voice-recovery-setup  # озвучить реплики «повторите, пожалуйста» (стек поднят)
```

### Репетиция отказов перед демо

Failover нельзя проверить, если Soniox нечем сломать. Управляемые сбои включаются
только явным флагом (`STT_DEBUG_FAULTS_ENABLED=true`), в обычной конфигурации
этих путей не существует. Взводится на одну реплику:

```bash
curl -X POST localhost:8010/debug/stt-fault \
     -H 'Content-Type: application/json' -d '{"mode":"midturn"}'
```

`open` — Soniox не поднимается; `midturn` — обрыв посреди речи с переигрыванием
буфера в GigaAM; `stall` — соединение живо, но финал не приходит (проверяет
5-секундный watchdog); `off` — снять взвод. После срабатывания следующая реплика
снова обычная.

Прогнать все три до защиты стоит: это единственный способ убедиться, что
деградация выглядит спокойно, а не как зависший экран.

### Аватары: внешность, голос, реплика при сбое

Аватар выбирает ученик кнопкой в сессии. Разделение ответственности:

- **Рендер — на клиенте.** `AVATAR_MODELS` в `TalkingHeadAvatar.tsx`: модель,
  ракурс (`cameraView`) и поправки кадра (`cameraTuning`) под геометрию каждого
  GLB. Серверу незачем знать `cameraDistance`.
- **Голос — на сервере.** `gateway/app/orchestrator/avatar_voice.py`: какой
  голос и какая служебная реплика связаны с профилем. Клиент присылает только
  `avatar_id`, а не произвольный `voice_id`.

`avatar_id` едет и на `user_message`, и на `speech_start`, и хранится в сессии —
поэтому голос одинаков независимо от того, набрал ученик текст или сказал
голосом. Примерять модели и слушать голоса удобно на `/avatar-lab` и
`/emotion-lab`.

**Реплика при потерянной реплике.** Если голосовой ход потерян окончательно —
оба движка распознавания отказали, соединение оборвалось или финал пришёл
пустым — персонаж переспрашивает вслух своим голосом, вместо красного баннера.
При failover на локальный движок это не срабатывает: там аудио переспрашивается
из буфера целиком и ничего не теряется.

Аудио готовится заранее, потому что отказ TTS — сам по себе один из способов
потерять ход: просить синтез в этот момент значит просить помощи у того, кто уже
упал. `make voice-recovery-setup` перебирает все сочетания профиля аватара с
персонами сценариев, потому что аватар переключается посреди сессии.

Фраза по умолчанию не содержит прошедшего времени: род персонажа заранее
неизвестен, а «не расслышал» и «не расслышала» разошлись бы. У Тома своя.

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

## Attribution

Рендер аватара использует [TalkingHead](https://github.com/met4citizen/TalkingHead)
и [HeadAudio](https://github.com/met4citizen/HeadAudio) авторства Mika
Suominen, распространяемые по лицензии MIT:

- Лицензия TalkingHead — устанавливается через npm (`@met4citizen/talkinghead`).
- Лицензия HeadAudio — `services/frontend/public/vendor/headaudio/LICENSE`.

Уведомления об авторских правах в исходных файлах этих компонентов сохранены.
