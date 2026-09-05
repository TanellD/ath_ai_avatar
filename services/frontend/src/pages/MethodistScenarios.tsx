/**
 * Список сценариев — Claude.md §2, §11.
 *
 * Первый шаг демо: «методист выбирает шаблон, меняет два поля, запускает — за
 * минуту». Отсюда одно проектное решение: шаблон не редактируется на месте, а
 * копируется. Иначе первый же прогон испортит эталон для всей команды.
 *
 * Галочка «база знаний» (issue #11, RAG) — здесь же, на карточке, а не в
 * отдельном редакторе сценария: полноценного конструктора (issue #24) пока
 * нет, а откладывать RAG до него означало бы откладывать саму фичу.
 */

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { knowledgeApi, scenarioApi } from '@/api/client';
import type { ScenarioSummary } from '@/contracts/events';
import type { KnowledgeDocInfo } from '@/contracts/knowledge';

export function MethodistScenarios() {
  const [items, setItems] = useState<ScenarioSummary[]>([]);
  const [docs, setDocs] = useState<Record<string, KnowledgeDocInfo | null>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    scenarioApi
      .list()
      .then((data) => {
        setItems(data);
        for (const item of data) {
          if (item.knowledge_base_enabled) void refreshDoc(item.id);
        }
      })
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setLoading(false));
  }, []);

  async function refreshDoc(scenarioId: string) {
    try {
      const list = await knowledgeApi.list(scenarioId);
      setDocs((current) => ({ ...current, [scenarioId]: list[0] ?? null }));
    } catch {
      // Молча: rag-service может быть не поднят локально — это не должно
      // ронять страницу со списком сценариев, только скрыть статус документа.
    }
  }

  async function toggleKnowledgeBase(item: ScenarioSummary) {
    setBusy(item.id);
    try {
      const full = await scenarioApi.get(item.id);
      const updated = await scenarioApi.save({
        ...full,
        knowledge_base_enabled: !full.knowledge_base_enabled,
      });
      setItems((current) =>
        current.map((s) =>
          s.id === item.id ? { ...s, knowledge_base_enabled: updated.knowledge_base_enabled } : s,
        ),
      );
      if (updated.knowledge_base_enabled) await refreshDoc(item.id);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function uploadFile(scenarioId: string, file: File) {
    setBusy(scenarioId);
    try {
      const doc = await knowledgeApi.upload(scenarioId, file);
      setDocs((current) => ({ ...current, [scenarioId]: doc }));
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function deleteDoc(scenarioId: string) {
    setBusy(scenarioId);
    try {
      await knowledgeApi.remove(scenarioId);
      setDocs((current) => ({ ...current, [scenarioId]: null }));
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <p className="page">Загружаем сценарии…</p>;
  if (error) return <p className="page page--error">Не удалось загрузить сценарии: {error}</p>;

  return (
    <main className="page page--wide">
      <section className="card hero-card">
        <span className="eyebrow">Библиотека</span>
        <h1>Сценарии</h1>
        <p className="lead">
          Персонаж, этапы и рубрика хранятся вместе. Выберите сценарий, чтобы пройти его
          самостоятельно, или посмотрите готовые отчёты в разделе «Сессии».
        </p>
      </section>

      {items.length === 0 && <p>Сценариев пока нет.</p>}

      <section className="scenario-grid">
        {items.map((item) => {
          const doc = docs[item.id];
          return (
            <article key={item.id} className="product">
              <div className="product-ic">
                <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="m12 3.6 8.4 4.4-8.4 4.4-8.4-4.4Z" />
                  <path d="m3.6 12.4 8.4 4.4 8.4-4.4" />
                </svg>
              </div>
              <h3>{item.title}</h3>
              <p>
                Персонаж: {item.persona_name} · этапов: {item.stages_count} · критериев в
                рубрике: {item.rubric_count}
              </p>

              <div className="knowledge-panel">
                <label className="knowledge-panel__toggle">
                  <input
                    type="checkbox"
                    checked={item.knowledge_base_enabled}
                    disabled={busy === item.id}
                    onChange={() => void toggleKnowledgeBase(item)}
                  />
                  <span>Использовать базу знаний (RAG)</span>
                </label>

                {item.knowledge_base_enabled && (
                  <div className="knowledge-panel__body">
                    {doc ? (
                      <div className="knowledge-panel__doc">
                        <span className="bento-pill">
                          {doc.filename} · {doc.chunk_count} фрагм.
                        </span>
                        <button
                          type="button"
                          className="knowledge-panel__remove"
                          disabled={busy === item.id}
                          onClick={() => void deleteDoc(item.id)}
                        >
                          Удалить
                        </button>
                      </div>
                    ) : (
                      <label className="knowledge-panel__upload">
                        Загрузить документ (.txt, .md)
                        <input
                          type="file"
                          accept=".txt,.md"
                          disabled={busy === item.id}
                          onChange={(event) => {
                            const file = event.target.files?.[0];
                            if (file) void uploadFile(item.id, file);
                            event.target.value = '';
                          }}
                        />
                      </label>
                    )}
                  </div>
                )}
              </div>

              <div className="product-foot">
                <span>{item.stages_count} этапа(ов)</span>
                <Link className="arrow-btn" to={`/session/${item.id}`} aria-label={`Пройти «${item.title}»`}>
                  <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M4.5 12h14" />
                    <path d="m12.5 6 6 6-6 6" />
                  </svg>
                </Link>
              </div>
            </article>
          );
        })}
      </section>

      {/* TODO: редактор сценария (§7, issue #24) — правка полей персонажа,
          этапов и рубрики, плюс копирование шаблона перед правкой. */}
    </main>
  );
}
