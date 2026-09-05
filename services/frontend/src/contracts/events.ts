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
}

export interface Ping {
  type: 'ping';
}

export interface SpeechStart {
  type: 'speech_start';
  capture_id: string;
  interrupts: number | null;
  mode: 'ptt' | 'hands_free_candidate';
  audio_format: 'pcm_s16le';
  sample_rate: 16000;
  num_channels: 1;
}

export interface SpeechEnd {
  type: 'speech_end';
  capture_id: string;
}

export interface SpeechAbort {
  type: 'speech_abort';
  capture_id: string;
}

export type ClientEvent = UserMessage | SpeechStart | SpeechEnd | SpeechAbort | Ping;

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
  capture_id: string;
  provider_epoch: number;
  provider: string;
  text: string;
  is_final: boolean;
  stt_confidence: number | null;
}

export interface SpeechStartedEvent {
  type: 'speech_started';
  gen_id: number;
  capture_id: string;
}

/**
 * [STT] Внутри одной capture распознавание ушло на резервный провайдер.
 * UI ориентируется на `partials_available`, а не на имя движка.
 */
export interface VoiceProviderSwitchedEvent {
  type: 'voice_provider_switched';
  gen_id: number;
  capture_id: string;
  provider_epoch: number;
  provider: string;
  partials_available: boolean;
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
  /** Персонаж уже сказал это вслух: сбросить захват, но баннер не показывать. */
  spoken: boolean;
}

export type ServerEvent =
  | TokenEvent
  | AudioChunkEvent
  | SubtitleEvent
  | SpeechStartedEvent
  | TranscriptEvent
  | VoiceProviderSwitchedEvent
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

/** Внешность и голос по умолчанию. Одна запись на модель, переиспользуется сценариями. */
export interface AvatarProfile {
  id: string;
  title: string;
  model_url: string;
  body: 'F' | 'M';
  voice_id: string | null;
  recovery_line: string | null;
}

export interface Persona {
  name: string;
  role: string;
  character: string;
  mood: Mood;
  difficulty: number;
  avatar_id: string;
  /** Перекрывает голос аватара; null — берётся голос аватара. */
  voice_id: string | null;
  /** Перекрывает фразу аватара на случай потерянной реплики. */
  recovery_line: string | null;
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
