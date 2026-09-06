/**
 * HTTP-клиенты gateway, scenario-service и ai-service.
 *
 * Откуда берутся адреса и почему их две схемы — см. `origins.ts`.
 */

import { origins } from '@/api/origins';
import type {
  GenSummary,
  LoadStats,
  SessionPath,
  SessionSummary,
  Span,
} from '@/contracts/admin';
import type {
  Persona,
  Report,
  RubricItem,
  Scenario,
  ScenarioSlot,
  ScenarioSummary,
  SessionSummaryItem,
  Stage,
} from '@/contracts/events';

const { api: API_URL, ws: WS_URL, scenario: SCENARIO_URL, ai: AI_URL } = origins;

/**
 * Ошибка с кодом ответа.
 *
 * Нужна, чтобы отличать «данных ещё нет» от настоящей поломки: у отчёта 404 —
 * это штатное «сессия не завершена», и показывать на нём текст ошибки нельзя.
 * Наследуется от Error, поэтому старые `catch (cause: Error)` не трогаем.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });

  if (!response.ok) {
    const body = await response.text();
    throw new ApiError(response.status, `${response.status} ${response.statusText}: ${body}`);
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export interface CreateSessionResponse {
  session_id: string;
  scenario_id: string;
  ws_url: string;
  /**
   * Сценарий ЭТОГО прогона: детали слотов уже подставлены сервером. Клиент
   * берёт его отсюда, а не из scenario-service, иначе бриф и шапка показали
   * бы неподставленный текст — а персонаж знал бы подставленный.
   */
  scenario: Scenario;
}

/** Ровно то, что нужно клиенту после переподключения. */
export interface SessionGeneration {
  current_gen: number;
}

export const gatewayApi = {
  createSession(scenarioId: string): Promise<CreateSessionResponse> {
    return request(`${API_URL}/sessions`, {
      method: 'POST',
      body: JSON.stringify({ scenario_id: scenarioId }),
    });
  },

  getSession(sessionId: string): Promise<SessionGeneration> {
    return request(`${API_URL}/sessions/${sessionId}`);
  },

  async listSessions(): Promise<SessionSummaryItem[]> {
    const data = await request<{ items: SessionSummaryItem[] }>(`${API_URL}/sessions`);
    return data.items;
  },

  getReport(sessionId: string): Promise<Report> {
    return request(`${API_URL}/sessions/${sessionId}/report`);
  },

  /** Пересчитать оценку заново — когда отчёт сделан заглушкой или не сделан. */
  rebuildReport(sessionId: string): Promise<Report> {
    return request(`${API_URL}/sessions/${sessionId}/report`, { method: 'POST' });
  },

  sessionSocketUrl(sessionId: string): string {
    return `${WS_URL}/ws/session/${sessionId}`;
  },
};

export const adminApi = {
  async listSessions(): Promise<SessionSummary[]> {
    const data = await request<{ items: SessionSummary[] }>(`${API_URL}/admin/sessions`);
    return data.items;
  },

  getSessionPath(sessionId: string): Promise<SessionPath> {
    return request(`${API_URL}/admin/sessions/${sessionId}/path`);
  },

  async listGens(sessionId: string): Promise<GenSummary[]> {
    const data = await request<{ items: GenSummary[] }>(
      `${API_URL}/admin/sessions/${sessionId}/gens`,
    );
    return data.items;
  },

  async listSpans(sessionId: string, genId: number): Promise<Span[]> {
    const data = await request<{ items: Span[] }>(
      `${API_URL}/admin/sessions/${sessionId}/gens/${genId}/spans`,
    );
    return data.items;
  },

  getLoad(): Promise<LoadStats> {
    return request(`${API_URL}/admin/load`);
  },
};

export const scenarioApi = {
  async list(): Promise<ScenarioSummary[]> {
    const data = await request<{ items: ScenarioSummary[] }>(`${SCENARIO_URL}/scenarios`);
    return data.items;
  },

  get(scenarioId: string): Promise<Scenario> {
    return request(`${SCENARIO_URL}/scenarios/${scenarioId}`);
  },

  save(scenario: Scenario): Promise<Scenario> {
    return request(`${SCENARIO_URL}/scenarios/${scenario.id}`, {
      method: 'PUT',
      body: JSON.stringify(scenario),
    });
  },

  copy(scenarioId: string, newId: string): Promise<Scenario> {
    return request(
      `${SCENARIO_URL}/scenarios/${scenarioId}/copy?new_id=${encodeURIComponent(newId)}`,
      { method: 'POST' },
    );
  },

  remove(scenarioId: string): Promise<void> {
    return request(`${SCENARIO_URL}/scenarios/${scenarioId}`, { method: 'DELETE' });
  },
};

/** Черновик, а не готовый сценарий: `id` задаёт методист, он же адрес страницы. */
export interface ScenarioDraft {
  title: string;
  persona: Persona;
  stages: Stage[];
  rubric: RubricItem[];
  tags: string[];
  briefing: string;
  slots: ScenarioSlot[];
}

/**
 * Генерация черновиков в редакторе сценария.
 *
 * Браузер обращается к ai-service напрямую, минуя gateway, — как и к
 * scenario-service за CRUD: оркестратору нечего добавить к разовому вызову
 * модели, а ключи остаются в сервисе.
 */
export const aiApi = {
  draftScenario(brief: string, stagesCount: number, rubricCount: number): Promise<ScenarioDraft> {
    return request(`${AI_URL}/scenario/draft`, {
      method: 'POST',
      body: JSON.stringify({
        brief,
        stages_count: stagesCount,
        rubric_count: rubricCount,
      }),
    });
  },

  async draftRubric(
    title: string,
    persona: Persona,
    stages: Stage[],
    count: number,
  ): Promise<RubricItem[]> {
    const data = await request<{ items: RubricItem[] }>(`${AI_URL}/scenario/rubric`, {
      method: 'POST',
      body: JSON.stringify({ title, persona, stages, count }),
    });
    return data.items;
  },
};
