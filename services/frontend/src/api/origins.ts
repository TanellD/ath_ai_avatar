/**
 * Адреса сервисов — Claude.md §5.
 *
 * Умеет две схемы, и это не избыточность, а разные условия работы.
 *
 * **Один origin (по умолчанию).** Пути относительные, а перед сервисами стоит
 * прокси: nginx в проде, dev-сервер Vite локально. Так адрес перестаёт быть
 * параметром сборки — тот же образ работает и на localhost, и за туннелем.
 * Без этого HTTPS с телефона просто недостижим: `ws://` со страницы по https
 * браузер режет как mixed content, а поднимать четыре туннеля и четыре
 * сертификата под четыре сервиса — не вариант.
 *
 * **Раздельные адреса (VITE_*).** Прежняя схема: браузер ходит в каждый сервис
 * напрямую по своему порту. Остаётся как явное переопределение — переменная
 * окружения сильнее умолчания.
 *
 * Хардкода хостов здесь нет ни в одной ветке: в референсном проекте он есть
 * (`http://83.151.2.86:7533/...` прямо в сервисе), и это ровно та вещь, которая
 * ломается при переносе демо на другую машину.
 */

/** То немногое, что нужно от `window.location`, — чтобы функция была чистой. */
export interface OriginLocation {
  protocol: string;
  host: string;
}

export interface ServiceOrigins {
  /** REST шлюза. */
  api: string;
  /**
   * База сокета сессии — без пути: маршрут шлюза уже начинается с `/ws`
   * (`gatewayApi.sessionSocketUrl` дописывает `/ws/session/:id`), и второй
   * префикс дал бы `/ws/ws/session/...`. Абсолютная: `new WebSocket()`
   * относительный путь не принимает.
   */
  ws: string;
  scenario: string;
  ai: string;
  /** Сокет speech-service, нужен только лаборатории эмоций. */
  speechWs: string;
}

/** Пути прокси. Обязаны совпадать с nginx.conf и vite.config.ts. */
const PATHS = {
  api: '/api',
  scenario: '/scenario',
  ai: '/ai',
  speechWs: '/speech',
} as const;

type Env = Partial<Record<string, string | undefined>>;

function trimSlash(value: string): string {
  return value.replace(/\/+$/, '');
}

export function resolveOrigins(env: Env, location: OriginLocation): ServiceOrigins {
  // https → wss обязательно: смешивать протоколы браузер не даст.
  const wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const sameOrigin = `${location.protocol}//${location.host}`;
  const sameOriginWs = `${wsProtocol}//${location.host}`;

  const pick = (value: string | undefined, fallback: string): string =>
    value?.trim() ? trimSlash(value.trim()) : fallback;

  return {
    api: pick(env.VITE_API_URL, sameOrigin + PATHS.api),
    ws: pick(env.VITE_WS_URL, sameOriginWs),
    scenario: pick(env.VITE_SCENARIO_API_URL, sameOrigin + PATHS.scenario),
    ai: pick(env.VITE_AI_API_URL, sameOrigin + PATHS.ai),
    speechWs: pick(env.VITE_SPEECH_WS_URL, sameOriginWs + PATHS.speechWs),
  };
}

/**
 * Заглушка для не-браузерных сред. Vitest в этом проекте запускается в node,
 * без jsdom (см. отсутствие `environment` в vite.config.ts), а модуль
 * вычисляется на импорте — без этой ветки любой тест, который тянет за собой
 * `client.ts`, падал бы на `window is not defined`. В бандле ветка мертва.
 */
const CURRENT_LOCATION: OriginLocation =
  typeof window === 'undefined'
    ? { protocol: 'http:', host: 'localhost' }
    : window.location;

export const origins: ServiceOrigins = resolveOrigins(
  import.meta.env as Env,
  CURRENT_LOCATION,
);
