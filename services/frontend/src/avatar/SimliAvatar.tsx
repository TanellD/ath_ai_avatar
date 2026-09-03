/**
 * Рендер персонажа — Claude.md §10.
 *
 * Основной вариант: Simli (audio→video, managed, ~$0,009/мин, чистый API).
 * Запасной для демо без интернета: bitHuman (локально, CPU).
 *
 * Перед подключением проверить статус SDK: репозиторий Simli переведён в
 * read-only, и это единственная внешняя зависимость, чей отвал ломает демо
 * визуально, а не функционально.
 *
 * Не брать (проверено в §10): HeyGen LiveAvatar — латентность 1-2 с, проваливает
 * метрику 1; MuseTalk — высокий риск, русского нет в заявленных языках; Tavus —
 * только рендер, его Raven и Sparrow дублируют наш оркестратор.
 */

import { useEffect, useRef } from 'react';

import type { PlaybackClock } from '@/audio/PlaybackClock';
import { LipSync } from '@/avatar/LipSync';

interface Props {
  clock: PlaybackClock;
  /** Заглушка активна, пока нет ключа Simli. */
  placeholder?: boolean;
}

export function SimliAvatar({ clock, placeholder = true }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const context = canvas.getContext('2d');
    if (!context) return;

    // Липсинк берёт время у часов аудио — единственный допустимый источник (§3).
    const lipSync = new LipSync(clock, ({ openness }) => {
      context.clearRect(0, 0, canvas.width, canvas.height);

      // Схематичное лицо-заглушка: круг и рот, раскрытие которого пропорционально
      // openness. Смысл — видеть, что часы работают, до подключения Simli.
      context.fillStyle = '#d9d2c5';
      context.beginPath();
      context.arc(canvas.width / 2, canvas.height / 2, 90, 0, Math.PI * 2);
      context.fill();

      context.fillStyle = '#2b2b2b';
      const mouthHeight = 6 + openness * 40;
      context.beginPath();
      context.ellipse(
        canvas.width / 2,
        canvas.height / 2 + 40,
        34,
        mouthHeight / 2,
        0,
        0,
        Math.PI * 2,
      );
      context.fill();
    });

    lipSync.start();
    return () => lipSync.stop();
  }, [clock]);

  return (
    <div className="avatar">
      <canvas ref={canvasRef} width={320} height={320} />
      {placeholder && (
        <p className="avatar__hint">
          Заглушка рендера. Simli подключается при заданном VITE_SIMLI_API_KEY.
        </p>
      )}
    </div>
  );
}
