/**
 * Обстановка перед разговором — Claude.md §7.
 *
 * Показывается в двух местах и по-разному наполненная:
 *
 *   - на превью кейса (`/scenarios/:id`) — с примерами методиста: страница
 *     «что это за кейс» обязана открываться мгновенно и бесплатно;
 *   - в оверлее старта — с деталями ЭТОГО прогона, которые gateway подобрал
 *     при создании сессии. Это последний экран перед разговором, и прочитанное
 *     здесь совпадает с тем, что знает персонаж.
 *
 * Абзацы бьются по пустой строке: бриф пишет человек в textarea, и переносы в
 * нём осмысленные.
 */

interface ScenarioBriefingProps {
  text: string;
}

export function ScenarioBriefing({ text }: ScenarioBriefingProps) {
  const paragraphs = text
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);

  if (paragraphs.length === 0) return null;

  return (
    <div className="briefing">
      {paragraphs.map((paragraph, index) => (
        <p key={index} className="briefing__paragraph">
          {paragraph}
        </p>
      ))}
    </div>
  );
}
