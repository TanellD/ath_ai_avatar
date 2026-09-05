"""Аватар: внешность и голос по умолчанию, одна запись на модель.

Отделено от `Persona` намеренно. Модель переиспользуется между сценариями, а
характер — нет: одно и то же лицо может достаться и закупщику, и кандидату,
и звучать они должны по-разному. Поэтому аватар задаёт голос и фразу
восстановления *по умолчанию*, а персона при необходимости их перекрывает.

Добавление нового аватара — запись в реестре scenario-service, без правок кода.
"""

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ath_contracts.scenario import Persona

DEFAULT_AVATAR_ID = "aith"


class AvatarProfile(BaseModel):
    id: str
    title: str
    model_url: str = Field(description="Что грузит TalkingHead, относительно корня фронтенда")
    body: Literal["F", "M"] = Field(
        default="F", description="Тип рига TalkingHead: от него зависят поза и жесты"
    )
    voice_id: str | None = Field(
        default=None,
        description="Голос у TTS-провайдера. None — голос по умолчанию из конфига сервиса.",
    )
    recovery_line: str | None = Field(
        default=None,
        description=(
            "Что аватар говорит, когда реплика собеседника потерялась. "
            "None — общая нейтральная фраза."
        ),
    )


DEFAULT_RECOVERY_LINE = "Простите, вас плохо слышно. Повторите, пожалуйста."
"""Фраза по умолчанию, когда ни у аватара, ни у персоны своей нет.

Без прошедшего времени намеренно: «не расслышал» и «не расслышала» разошлись бы
по роду персонажа, а настоящее время одинаково годится всем. Вина не
перекладывается на собеседника, и прямо запрошен повтор.
"""


def resolve_voice(persona: "Persona", avatar: AvatarProfile | None) -> str | None:
    """Голос персонажа: своё поле персоны важнее голоса аватара.

    Одна модель может достаться разным характерам, поэтому персона имеет право
    звучать иначе. None означает «голос по умолчанию из конфига сервиса».
    """
    if persona.voice_id:
        return persona.voice_id
    return avatar.voice_id if avatar is not None else None


def resolve_recovery_line(persona: "Persona", avatar: AvatarProfile | None) -> str:
    """Фраза на случай потерянной реплики, по той же цепочке приоритетов."""
    if persona.recovery_line:
        return persona.recovery_line
    if avatar is not None and avatar.recovery_line:
        return avatar.recovery_line
    return DEFAULT_RECOVERY_LINE
