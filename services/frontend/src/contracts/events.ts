/**
 * Контракты WebSocket — зеркало packages/contracts/ath_contracts/events.py.
 *
 * Пока написано руками. Сгенерировать из JSON Schema:
 *   npm run gen:contracts        (см. scripts/gen-ts-contracts.ps1)
 *
 * Расхождение этого файла с питоновским контрактом ломает фильтрацию по
 * gen_id молча — событие просто не распознаётся и отбрасывается. Если правите
 * одну сторону, правьте обе.
 */

export type Action = 'stay' | 'next_stage' | 'finish' | 'evaluate';
export type SessionStatus = 'active' | 'finished' | 'abandoned';
export type TurnRole = 'user' | 'agent';
export type Mood = 'neutral' | 'irritated' | 'friendly';
export type Emotion = Mood | 'angry' | 'sad' | 'excited' | 'surprised';
export type AvatarId = 'avatar-aith' | 'tom-avatar';

// --------------------------------------------------------- клиент → сервер

/**
 * Реплика пользователя. Отправка = перебивание (Claude.md §6).
 *
 * `interrupts` — gen_id поколения, которое перебиваем, либо null если
 * персонаж молчал. К моменту отправки клиент УЖЕ вызвал cancelPlayback().
 */
export interface UserMessage {
  type: 'user_message';
  text: string;
  interrupts: number | null;
  /** Профиль рендера; сервер сам выбирает связанный с ним голос. */
  avatar_id: AvatarId;
}

export interface Ping {
  type: 'ping';
}

export type ClientEvent = UserMessage | Ping;

// [STT] Голосовая фаза — объявлено в питоновском контракте, здесь появится
// вместе с реализацией. См. docs/stt-phase.md.
//   speech_start { interrupts }
//   user_audio   { seq, data, format }
//   speech_end   {}

// --------------------------------------------------------- сервер → клиент

export interface TokenEvent {
  type: 'token';
  gen_id: number;
  text: string;
}

export interface AudioChunkEvent {
  type: 'audio_chunk';
  gen_id: number;
  seq: number;
  /** base64 */
  data: string;
  format: string;
  emotion: Emotion;
}

export interface SubtitleEvent {
  type: 'subtitle';
  gen_id: number;
  text: string;
  /** Относительно начала аудио ПОКОЛЕНИЯ, не сессии. */
  start_ms: number;
  end_ms: number;
}

/** [STT] Не приходит в текстовой фазе. */
export interface TranscriptEvent {
  type: 'transcript';
  gen_id: number;
  text: string;
  is_final: boolean;
  stt_confidence: number | null;
}

export interface ActionEvent {
  type: 'action';
  gen_id: number;
  action: Action;
  stage_id: string;
}

export interface CancelEvent {
  type: 'cancel';
  gen_id: number;
}

export interface ReportEvent {
  type: 'report';
  gen_id: number;
  session_id: string;
  report: Report;
}

export interface ErrorEvent {
  type: 'error';
  gen_id: number | null;
  code: string;
  message: string;
}

export type ServerEvent =
  | TokenEvent
  | AudioChunkEvent
  | SubtitleEvent
  | TranscriptEvent
  | ActionEvent
  | CancelEvent
  | ReportEvent
  | ErrorEvent;

// ------------------------------------------------------------------ модели

export interface Turn {
  role: TurnRole;
  text: string;
  stage_id: string;
  ts: number;
  /** [STT] null в текстовой фазе. */
  stt_confidence: number | null;
  /** [STT] null в текстовой фазе. */
  audio_ref: string | null;
}

/** [STT] Всегда null в текстовой фазе — см. report.py. */
export interface AudioRef {
  turn: number;
  start_ms: number;
  end_ms: number;
}

export interface CriterionScore {
  criterion_id: string;
  score: number;
  /** Дословная цитата из реплики сотрудника. Обязательна (§7). */
  evidence: string;
  comment: string;
  audio_ref: AudioRef | null;
  stt_confidence: number | null;
}

export interface Report {
  session_id: string;
  verdict: string;
  total_score: number;
  scores: CriterionScore[];
  transcript: Turn[];
  duration_sec: number;
  stages_completed: number;
  stages_total: number;
}

export interface Persona {
  name: string;
  role: string;
  character: string;
  mood: Mood;
  difficulty: number;
  voice_id: string | null;
}

export interface Stage {
  id: string;
  goal: string;
  agent_opening: string;
  completion_criteria: string;
  max_turns: number;
}

export interface RubricItem {
  id: string;
  name: string;
  description: string;
  scale: number;
  weight: number;
}

export interface Scenario {
  id: string;
  title: string;
  persona: Persona;
  stages: Stage[];
  rubric: RubricItem[];
}

export interface ScenarioSummary {
  id: string;
  title: string;
  persona_name: string;
  stages_count: number;
  rubric_count: number;
}
