/**
 * Что доступно только в безопасном контексте (HTTPS или localhost).
 *
 * Понадобилось ради телефона. На десктопе разработчик всегда на localhost и
 * никогда этого не видит; стоит открыть стенд с телефона по обычному http — и
 * ломаются сразу две вещи, причём молча.
 *
 * `crypto.randomUUID()` — secure-context-only, и на http его просто нет. Он
 * вызывался первой строкой обработчика нажатия на кнопку записи, бросал
 * `TypeError` синхронно, а границы ошибок в приложении нет: React логировал
 * исключение, состояние не менялось, баннер не показывался. Кнопка выглядела
 * исправной и не делала ничего.
 *
 * `navigator.mediaDevices` там же не определён. Прежняя проверка отвечала на
 * это «Браузер не поддерживает захват речи» — неправда, которая уводит в
 * сторону: браузер поддерживает, не хватает HTTPS.
 */

export interface MicAvailability {
  available: boolean;
  /** Готовое объяснение пользователю. Пусто, когда всё в порядке. */
  reason: string;
}

const NEEDS_HTTPS =
  'Микрофон доступен только по HTTPS. Откройте страницу по защищённому адресу '
  + 'или пишите ответы текстом.';

const NO_SUPPORT = 'Браузер не поддерживает захват речи — пишите ответы текстом.';

/**
 * Разделяет «нет HTTPS» и «браузер не умеет»: пользователю это разные новости,
 * и чинятся они по-разному.
 */
export function checkMicAvailability(
  scope: Pick<Window, 'isSecureContext'> & {
    navigator: Pick<Navigator, 'mediaDevices'>;
    AudioWorkletNode?: unknown;
  },
): MicAvailability {
  if (!scope.isSecureContext) return { available: false, reason: NEEDS_HTTPS };
  if (!scope.navigator.mediaDevices?.getUserMedia || !scope.AudioWorkletNode) {
    return { available: false, reason: NO_SUPPORT };
  }
  return { available: true, reason: '' };
}

export function micAvailability(): MicAvailability {
  return checkMicAvailability(window);
}

/**
 * `crypto.randomUUID` с запасным путём.
 *
 * Формат обязан остаться настоящим UUID v4: `capture_id` уходит на сервер, где
 * контракт объявляет его как `UUID` (ath_contracts/api.py), и произвольная
 * строка не прошла бы валидацию.
 */
export function randomUuid(source: Crypto = crypto): string {
  if (typeof source.randomUUID === 'function') return source.randomUUID();

  const bytes = new Uint8Array(16);
  source.getRandomValues(bytes);
  // Версия 4 и вариант 10xx — иначе это не UUID v4, а просто 16 байт.
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;

  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
