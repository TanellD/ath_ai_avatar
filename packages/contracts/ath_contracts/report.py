"""Отчёт методисту — Claude.md §7.

Отчёт — главный интерфейс методиста. Каждый балл обязан быть проверяем за
десять секунд, иначе методист начнёт слушать/читать историю целиком и продукт
потеряет смысл. Отсюда жёсткое требование: `evidence` обязателен и непуст.
"""

from pydantic import BaseModel, Field

from ath_contracts.session import Turn


class AudioRef(BaseModel):
    """Указатель на фрагмент аудио под цитатой — Claude.md §7.

    [STT] В текстовой фазе не заполняется никогда. Модель объявлена сейчас,
    потому что при голосовом вводе цитата перестаёт быть истиной (STT ошибается
    ровно на числах, ценах и названиях — то есть на содержании балла), и
    проверяемость восстанавливается точечным прослушиванием этой фразы.
    См. docs/stt-phase.md.
    """

    turn: int
    start_ms: int
    end_ms: int


class CriterionScore(BaseModel):
    criterion_id: str
    score: int = Field(ge=0)
    evidence: str = Field(
        min_length=1,
        description=(
            "Дословная цитата из реплики пользователя. Без неё методист не может "
            "проверить оценку быстро — это главная гипотеза проекта, а не деталь "
            "оформления (§7)."
        ),
    )
    comment: str = ""

    # [STT] Всегда None в текстовой фазе.
    audio_ref: AudioRef | None = None
    stt_confidence: float | None = None


class Report(BaseModel):
    session_id: str
    verdict: str
    total_score: float
    scores: list[CriterionScore]
    transcript: list[Turn] = Field(default_factory=list)
    duration_sec: int
    stages_completed: int
    stages_total: int

    # Оба поля со значением по умолчанию намеренно: отчёт хранится в БД целиком
    # (ReportRow.payload) и перевалидируется при чтении, поэтому обязательное
    # поле сделало бы нечитаемыми все уже сохранённые отчёты.
    scenario_id: str = Field(
        default="",
        description="Чтобы экран отчёта мог подтянуть рубрику и показать "
        "названия критериев вместо их id. Пусто — отчёт старого формата",
    )
    model: str = Field(
        default="",
        description="Чем посчитана оценка, например anthropic/claude-opus-5 или "
        "mock. Отчёт заглушки иначе не отличить от настоящего, не читая вердикт",
    )
