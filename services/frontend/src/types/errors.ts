/**
 * Типизированные ошибки клиента.
 *
 * Форма позаимствована из референсного проекта
 * (`tatarby-main/frontend/src/composables/useVoiceChat.ts`) — там это одна из
 * немногих вещей, сделанных правильно: пользователь видит разное сообщение,
 * когда сломалась сеть и когда он не дал доступ к микрофону, а не единое
 * «что-то пошло не так».
 */

export type SessionErrorType =
  | 'permission'
  | 'websocket'
  | 'audio'
  | 'network'
  | 'server'
  | 'unknown';

export interface SessionError {
  type: SessionErrorType;
  /** Текст для пользователя, по-русски. */
  message: string;
  /** Техническая подробность для лога — пользователю не показывается. */
  details?: string;
}

const MESSAGES: Record<SessionErrorType, string> = {
  permission: 'Нет доступа к микрофону. Разрешите доступ в настройках браузера.',
  websocket: 'Соединение с сервером прервано. Пробуем переподключиться.',
  audio: 'Не удалось воспроизвести звук. Проверьте вывод аудио.',
  network: 'Сеть недоступна.',
  server: 'Сервер вернул ошибку.',
  unknown: 'Непредвиденная ошибка.',
};

export function sessionError(
  type: SessionErrorType,
  details?: string,
  message?: string,
): SessionError {
  return { type, message: message ?? MESSAGES[type], details };
}
