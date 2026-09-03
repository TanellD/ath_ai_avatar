# Миграции gateway

Первая ревизия ещё не сгенерирована — сделать это надо один раз, из работающего
контейнера, чтобы схема снялась с реальных моделей:

```bash
docker compose exec gateway alembic revision --autogenerate -m "initial schema"
docker compose exec gateway alembic upgrade head
```

Файл ревизии появится в `app/alembic/versions/` и должен попасть в git.

До первой миграции таблицы создаются автоматически при старте (см.
`app/db/engine.py` → `Base.metadata.create_all` в lifespan) — этого хватает для
скелета, но перед первым релизом путь должен остаться один: alembic.

`render_as_batch=True` включён в `env.py` безусловно: SQLite не умеет
`ALTER COLUMN` и требует пересоздания таблицы, а на Postgres этот режим ничего
не портит. Благодаря этому одни и те же ревизии применяются к обеим базам.
