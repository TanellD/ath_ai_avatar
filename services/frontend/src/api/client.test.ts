/**
 * Регресс-тест на живой прод-баг: `VITE_*_URL` в проде уже содержит `/api`
 * (Caddy отдаёт весь `/api/*` бэкенду, всё остальное — SPA-фолбэк), а
 * `client.ts` раньше в некоторых путях дописывал `/api` ещё раз. Итоговый
 * `/api/api/sessions` у Caddy не смэтчился ни с одним backend-маршрутом,
 * запрос падал в SPA-фолбэк и получал `index.html` вместо JSON —
 * `response.json()` рушился на `Unexpected token '<'`.
 *
 * `API_URL`/`WS_URL`/`SCENARIO_URL`/`AI_URL` в client.ts читаются из
 * `import.meta.env` один раз при импорте модуля, поэтому чтобы проверить
 * разные значения env — обязательны `vi.stubEnv` + `vi.resetModules()` +
 * динамический импорт перед каждым запросом.
 */

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

function jsonResponse(body: unknown = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('client.ts — построение URL, когда VITE_*_URL уже содержит /api', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_URL', 'https://tochkayasnosty.ru/api');
    vi.stubEnv('VITE_WS_URL', 'wss://tochkayasnosty.ru/api');
    vi.stubEnv('VITE_SCENARIO_API_URL', 'https://tochkayasnosty.ru/api');
    vi.stubEnv('VITE_AI_API_URL', 'https://tochkayasnosty.ru/api');
    vi.resetModules();
    // Каждый вызов — новый Response: тело можно прочитать только раз, а
    // mockResolvedValue отдавал бы один и тот же объект на все вызовы.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ items: [] }))),
    );
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  test('gatewayApi.createSession — ровно один /api', async () => {
    const { gatewayApi } = await import('./client');
    await gatewayApi.createSession('objection_price');

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe('https://tochkayasnosty.ru/api/sessions');
  });

  test('gatewayApi.getSession — ровно один /api', async () => {
    const { gatewayApi } = await import('./client');
    await gatewayApi.getSession('sess-1');

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe('https://tochkayasnosty.ru/api/sessions/sess-1');
  });

  test('gatewayApi.getReport — ровно один /api', async () => {
    const { gatewayApi } = await import('./client');
    await gatewayApi.getReport('sess-1');

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe('https://tochkayasnosty.ru/api/sessions/sess-1/report');
  });

  test('gatewayApi.sessionSocketUrl — ровно один /api, без query-мусора в пути', async () => {
    const { gatewayApi } = await import('./client');
    const url = gatewayApi.sessionSocketUrl('sess-1', 'tom-avatar');

    expect(url).toBe('wss://tochkayasnosty.ru/api/ws/session/sess-1?avatar_id=tom-avatar');
  });

  test('adminApi.listSessions — ровно один /api', async () => {
    const { adminApi } = await import('./client');
    await adminApi.listSessions();

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe('https://tochkayasnosty.ru/api/admin/sessions');
  });

  test('adminApi.getLoad — ровно один /api', async () => {
    const { adminApi } = await import('./client');
    await adminApi.getLoad();

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe('https://tochkayasnosty.ru/api/admin/load');
  });

  test('scenarioApi.list — ровно один /api', async () => {
    const { scenarioApi } = await import('./client');
    await scenarioApi.list();

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe('https://tochkayasnosty.ru/api/scenarios');
  });

  test('scenarioApi.get — ровно один /api', async () => {
    const { scenarioApi } = await import('./client');
    await scenarioApi.get('objection_price');

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe('https://tochkayasnosty.ru/api/scenarios/objection_price');
  });

  test('aiApi.draftScenario — ровно один /api, не голый localhost из дев-фолбэка', async () => {
    const { aiApi } = await import('./client');
    await aiApi.draftScenario({
      brief: 'тест',
      stagesCount: null,
      rubricCount: null,
      current: null,
    });

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe('https://tochkayasnosty.ru/api/scenario/draft');
  });

  test('aiApi.draftRubric — ровно один /api', async () => {
    const { aiApi } = await import('./client');
    await aiApi.draftRubric('Название', {
      name: 'Ирина',
      role: 'закупщик',
      character: 'скептична',
      mood: 'neutral',
      difficulty: 3,
      voice_id: null,
      holds_initiative: true,
    }, [], 3);

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe('https://tochkayasnosty.ru/api/scenario/rubric');
  });

  test('ни один запрос никогда не бьёт в /api/api', async () => {
    const { gatewayApi, adminApi, scenarioApi } = await import('./client');

    await gatewayApi.createSession('x');
    await gatewayApi.getSession('x');
    await adminApi.listSessions();
    await scenarioApi.list();

    for (const [url] of vi.mocked(fetch).mock.calls) {
      expect(String(url)).not.toContain('/api/api');
    }
  });
});
