"""Разбиение документа на фрагменты для эмбеддинга.

Простое разбиение по абзацам с ограничением длины и небольшим перехлёстом —
не семантический сплиттер. Документ базы знаний по задумке короткий (регламент
или прайс-лист), усложнять сверх самой ChromaDB незачем: см. app/core/config.py.
"""


def chunk_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Абзацы как единица деления; абзац длиннее max_chars режется с перехлёстом.

    Перехлёст нужен, чтобы факт на границе двух фрагментов не терялся целиком
    ни в одном эмбеддинге — иначе поиск по этому факту может не найти ничего.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []

    chunks: list[str] = []
    buffer = ""

    for paragraph in paragraphs:
        candidate = f"{buffer}\n\n{paragraph}" if buffer else paragraph

        if len(candidate) <= max_chars:
            buffer = candidate
            continue

        if buffer:
            chunks.append(buffer)
        buffer = paragraph

        # Абзац сам по себе длиннее лимита — режем окнами с перехлёстом.
        while len(buffer) > max_chars:
            chunks.append(buffer[:max_chars])
            buffer = buffer[max_chars - overlap_chars :]

    if buffer:
        chunks.append(buffer)

    return chunks
