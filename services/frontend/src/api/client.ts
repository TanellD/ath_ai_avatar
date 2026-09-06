/**
 * HTTP-клиенты gateway и scenario-service.
 *
 * Адреса приходят из VITE_*, подставляются на этапе сборки. Хардкода хостов в
 * коде нет — в референсном проекте он есть (`http://83.151.2.86:7533/...`
 * прямо в сервисе), и это ровно та вещь, которая ломается при переносе демо на
 * другую машину.
 */

import type {
  GenSummary,
  LoadStats,
  SessionPath,
  SessionSummary,
  Span,
} from '@/contracts/admin';
import type {
  Report,
  Scenario,
  ScenarioSummary,
  SessionSummaryItem,
} from '@/contracts/events';

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000';
const SCENARIO_URL = import.meta.env.VITE_SCENARIO_API_URL ?? 'http://localhost:8050';

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
};
