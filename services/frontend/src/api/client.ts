/**
 * HTTP-клиенты gateway, scenario-service и ai-service.
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
  AvatarId,
  Persona,
  Report,
  RubricItem,
  Scenario,
  ScenarioSlot,
  ScenarioSummary,
  SessionSummaryItem,
  Stage,
} from '@/contracts/events';

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000';
const SCENARIO_URL = import.meta.env.VITE_SCENARIO_API_URL ?? 'http://localhost:8050';
const AI_URL = import.meta.env.VITE_AI_API_URL ?? 'http://localhost:8030';

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

/**
 * Человекочитаемая причина отказа.
 *
 * FastAPI кладёт её в `detail`, и там уже готовый текст для пользователя
 * («сотрудник не сказал ни одной реплики — оценивать нечего»). Раньше в
 * сообщение уходило сырое тело целиком, и методист видел на экране
 * `409 Conflict: {"detail":"…"}` — фигурные скобки и кавычки поверх осмысленной
 * фразы. Код ответа остаётся в `ApiError.status`, его и проверяют вызывающие.
 */
async function errorMessage(response: Response): Promise<string> {
  const fallback = `${response.status} ${response.statusText}`;
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === 'string' && body.detail) return body.detail;
    return fallback;
  } catch {
    // Не JSON — например HTML от прокси, когда сервис не поднялся.
    return fallback;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });

  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
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

  /**
   * `avatarId` — то, что сотрудник выбрал ДО открытия сокета. Открывающая
   * реплика (персонаж говорит первым, §1) звучит раньше первого UserMessage/
   * SpeechStart — единственных событий, которые иначе несли бы avatar_id —
   * поэтому без query-параметра сервер озвучивал её дефолтным (женским)
   * голосом даже для Vincent/Tom. Дальнейшие ходы синхронизируются как
   * раньше, этим параметром только открывающая реплика.
   */
  sessionSocketUrl(sessionId: string, avatarId: AvatarId): string {
    return `${WS_URL}/ws/session/${sessionId}?avatar_id=${encodeURIComponent(avatarId)}`;
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

/**
 * Черновик, а не готовый сценарий: `id` задаёт методист, он же адрес страницы.
 *
 * `suggested_id` — необязательное поле: у настоящего ответа генерации оно
 * всегда есть (бэкенд гарантирует непустое значение, см.
 * `ai-service/app/scenario/drafts.py::_scenario_id`), а вот когда этот же тип
 * используется как `current` — снимок уже заполненной формы, отправляемый
 * обратно как контекст, — предлагать методисту нечего, поле просто не шлётся.
 */
export interface ScenarioDraft {
  title: string;
  suggested_id?: string;
  persona: Persona;
  stages: Stage[];
  rubric: RubricItem[];
  tags: string[];
  briefing: string;
  slots: ScenarioSlot[];
}

export interface DraftScenarioParams {
  brief: string;
  /** `null` — «реши сам»: методист не задал точное число (Claude.md §5). */
  stagesCount: number | null;
  rubricCount: number | null;
  /** Что методист уже заполнил в форме — черновик обязан это учесть. */
  current: ScenarioDraft | null;
}

/**
 * Сильная модель, сценарий редкий — минуты, а не секунды (`docs/engineering/latency-budget.md`
 * сюда не относится: это не ход диалога). Таймаута нет ни на клиенте SDK внутри
 * ai-service, ни здесь по умолчанию — без него зависший запрос держал бы кнопку
 * в «Собираем черновик…» бесконечно.
 */
const DRAFT_TIMEOUT_MS = 120_000;

/**
 * Генерация черновиков в редакторе сценария.
 *
 * Браузер обращается к ai-service напрямую, минуя gateway, — как и к
 * scenario-service за CRUD: оркестратору нечего добавить к разовому вызову
 * модели, а ключи остаются в сервисе.
 */
export const aiApi = {
  draftScenario({
    brief,
    stagesCount,
    rubricCount,
    current,
  }: DraftScenarioParams): Promise<ScenarioDraft> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), DRAFT_TIMEOUT_MS);

    return request<ScenarioDraft>(`${AI_URL}/scenario/draft`, {
      method: 'POST',
      signal: controller.signal,
      body: JSON.stringify({
        brief,
        stages_count: stagesCount,
        rubric_count: rubricCount,
        current,
      }),
    })
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === 'AbortError') {
          throw new Error('Модель не ответила за две минуты — попробуйте ещё раз');
        }
        throw cause;
      })
      .finally(() => clearTimeout(timer));
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
