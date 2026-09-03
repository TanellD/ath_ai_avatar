"""_strip_code_fence — узкая защита от одного конкретного формата ответа.

Найдено вживую через сторонний ANTHROPIC_BASE_URL (router.cheap): даже с
прямой инструкцией «без markdown-разметки» модель завернула валидный JSON в
```json ... ``` код-блок. Тест фиксирует эту находку и то, что защита не
превращается в regex-экстракцию JSON из произвольной прозы — см. докстринг
complete_json() про то, почему это сознательное решение.
"""

from app.llm.anthropic_provider import _strip_code_fence


def test_strips_fenced_json_with_language_tag() -> None:
    text = '```json\n{"classification": "complete", "reason": "ok"}\n```'
    assert _strip_code_fence(text) == '{"classification": "complete", "reason": "ok"}'


def test_strips_bare_fence_without_language_tag() -> None:
    text = '```\n{"a": 1}\n```'
    assert _strip_code_fence(text) == '{"a": 1}'


def test_plain_json_is_returned_unchanged() -> None:
    text = '{"classification": "complete", "reason": "ok"}'
    assert _strip_code_fence(text) == text


def test_free_text_is_returned_unchanged_not_regex_extracted() -> None:
    """Узкая защита, не экстракция: прозу с JSON где-то внутри не трогаем —
    json.loads() на ней упадёт со своей понятной ошибкой, а не будет
    подменена на «похоже сработало»."""
    text = 'Конечно! Вот классификация: {"classification": "complete"}'
    assert _strip_code_fence(text) == text
