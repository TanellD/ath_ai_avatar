# GigaAM worker

Изолированный внутренний сервис локального STT. Принимает только канонический
`PCM16LE mono 16 kHz` через `POST /transcribe`; пользовательское аудио не пишет
на диск и не логирует.

По умолчанию используется `v3_e2e_ctc` на CPU. Модель загружается один раз в
фоновом потоке, после чего `GET /ready` начинает возвращать `204`. Одновременно
выполняется одна транскрипция, ещё одна может ждать в ограниченной очереди.
Docker image использует закреплённые CPU-сборки `torch/torchaudio 2.10.0`, без
CUDA runtime.

Запуск профиля из корня репозитория:

```powershell
docker compose --profile gigaam up --build gigaam-worker speech-service
```

Для ручного переключения speech-service укажите в `.env`:

```dotenv
STT_PROVIDER=gigaam
```

Целевая failover-конфигурация оставляет Soniox основным движком:

```dotenv
STT_PROVIDER=soniox_gigaam
```

Первый запуск скачивает веса в Docker volume `gigaam_cache` и поэтому заметно
дольше последующих. Текущий адаптер закреплён на `gigaam==0.2.0`: официальный
short-form API принимает путь к файлу, поэтому уже нормализованный PCM передаётся
непосредственно в `forward` и decoder без временного WAV и повторного resampling.
Поскольку версия `0.2.0` ещё не опубликована в PyPI, зависимость закреплена на
официальном commit `7447938d791c4f3e643386ee22c33777004293a5`.

Проект GigaAM: https://github.com/salute-developers/GigaAM (лицензия MIT).
