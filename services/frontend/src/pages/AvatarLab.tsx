import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';

import {
  AVATAR_MODEL_LIST,
  AVATAR_MODELS,
  TalkingHeadAvatar,
  type AvatarPlaybackHandle,
} from '@/avatar/TalkingHeadAvatar';
import type { Emotion } from '@/contracts/events';

const EMOTIONS: Array<{ value: Emotion; label: string }> = [
  { value: 'neutral', label: 'Нейтрально' },
  { value: 'friendly', label: 'Дружелюбно' },
  { value: 'irritated', label: 'Раздражённо' },
  { value: 'angry', label: 'Сердито' },
  { value: 'sad', label: 'Грустно' },
  { value: 'excited', label: 'Воодушевлённо' },
  { value: 'surprised', label: 'Удивлённо' },
];

function selectedModel() {
  const requested = new URLSearchParams(window.location.search).get('model');
  return AVATAR_MODEL_LIST.find((model) => model.id === requested) ?? AVATAR_MODEL_LIST[0];
}

export function AvatarLab() {
  const model = selectedModel();
  const [avatar, setAvatar] = useState<AvatarPlaybackHandle | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleReady = useCallback((handle: AvatarPlaybackHandle) => {
    setAvatar(handle);
    setError(null);
  }, []);

  const handleError = useCallback((message: string) => setError(message), []);

  const changeModel = (modelId: string) => {
    window.location.assign(`/avatar-lab?model=${encodeURIComponent(modelId)}`);
  };

  return (
    <main className="emotion-lab">
      <section className="emotion-lab__stage">
        <TalkingHeadAvatar
          model={model}
          isSpeaking={false}
          onReady={handleReady}
          onError={handleError}
        />
      </section>

      <section className="emotion-lab__controls">
        <h1>Лаборатория моделей</h1>
        <p>Тестовая страница не меняет модель в сценариях.</p>
        {model.id === AVATAR_MODELS.tom.id && (
          <p>Эмоциональные ARKit-морфы Tom пока пустые; проверяем позу, idle и взгляд.</p>
        )}

        <label className="emotion-lab__field">
          Модель аватара
          <select value={model.id} onChange={(event) => changeModel(event.target.value)}>
            {AVATAR_MODEL_LIST.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>

        <p className="emotion-lab__meta">
          Файл: <code>{model.url}</code>
        </p>

        <p>
          <Link to={`/emotion-lab?model=${encodeURIComponent(model.id)}`}>
            Проверить речь и lip-sync этой модели
          </Link>
        </p>

        <div className="emotion-lab__buttons">
          {EMOTIONS.map((emotion) => (
            <button
              type="button"
              className="emotion-lab__emotion"
              key={emotion.value}
              disabled={!avatar}
              onClick={() => avatar?.setEmotion(emotion.value)}
            >
              {emotion.label}
            </button>
          ))}
        </div>

        {error && <p className="emotion-lab__error">Не удалось загрузить модель: {error}</p>}
      </section>
    </main>
  );
}
