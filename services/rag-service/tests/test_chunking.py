from app.knowledge.chunking import chunk_text


def test_short_text_is_one_chunk() -> None:
    assert chunk_text("Короткий регламент.", max_chars=800, overlap_chars=120) == [
        "Короткий регламент."
    ]


def test_paragraphs_are_grouped_until_limit() -> None:
    text = "Абзац один." + "\n\n" + "Абзац два."
    chunks = chunk_text(text, max_chars=800, overlap_chars=120)
    assert chunks == ["Абзац один.\n\nАбзац два."]


def test_long_paragraph_is_split_with_overlap() -> None:
    paragraph = "а" * 1000
    chunks = chunk_text(paragraph, max_chars=400, overlap_chars=50)

    assert len(chunks) > 1
    # Перехлёст: конец одного чанка встречается в начале следующего.
    assert chunks[0][-50:] == chunks[1][:50]


def test_empty_text_gives_no_chunks() -> None:
    assert chunk_text("   \n\n  ", max_chars=800, overlap_chars=120) == []
