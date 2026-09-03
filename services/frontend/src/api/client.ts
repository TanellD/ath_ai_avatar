/**
 * HTTP-клиенты gateway и scenario-service.
 *
 * Адреса приходят из VITE_*, подставляются на этапе сборки. Хардкода хостов в
 * коде нет — в референсном проекте он есть (`http://83.151.2.86:7533/...`
 * прямо в сервисе), и это ровно та вещь, которая ломается при переносе демо на
 * другую машину.
 */

import type { Report, Scenario, ScenarioSummary } from '@/contracts/events';

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000';
const SCENARIO_URL = import.meta.env.VITE_SCENARIO_API_URL ?? 'http://localhost:8050';

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export interface CreateSessionResponse {
  session_id: string;
  scenario_id: string;
  ws_url: string;
}

export const gatewayApi = {
  createSession(scenarioId: string): Promise<CreateSessionResponse> {
    return request(`${API_URL}/sessions`, {
      method: 'POST',
      body: JSON.stringify({ scenario_id: scenarioId }),
    });
  },

  getReport(sessionId: string): Promise<Report> {
    return request(`${API_URL}/sessions/${sessionId}/report`);
  },

  sessionSocketUrl(sessionId: string): string {
    return `${WS_URL}/ws/session/${sessionId}`;
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
