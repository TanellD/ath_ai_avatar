# STT benchmark

Один и тот же локальный corpus сравнивает Soniox и варианты GigaAM. Аудио и
результаты не коммитятся: они могут содержать голос и персональные данные.

1. Скопировать `manifest.example.jsonl` в `manifest.local.jsonl`.
2. Положить consented mono/обычные записи в `audio/` и указать пути в manifest.
3. Provider runner сохраняет JSONL вида `{"id":"...","text":"..."}`.
4. Посчитать качество:

```powershell
python benchmarks/stt/scoring.py `
  --manifest benchmarks/stt/manifest.local.jsonl `
  --hypotheses benchmarks/stt/results/soniox.jsonl
```

`critical_entities` и `negations` размечаются для каждой реплики вручную.
Scorer не содержит универсального списка «важных слов» и не подменяет
продуктовую разметку эвристикой.

Кроме quality runner каждого provider обязан записывать отдельно cold/warm
latency, first partial, finalization latency, RTF, RAM и hardware metadata.
