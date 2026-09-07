"""Голос и служебные реплики по профилю аватара.

Клиент присылает только id профиля, а не произвольный voice_id: так тестовый
Tom получает свой голос, не меняя persona сценария и основной голос avatar-aith.

Здесь же живёт фраза, которую персонаж говорит вслух, когда голосовой ход
потерян окончательно. Она обязана звучать тем же голосом, что и обычная речь,
поэтому источник у них один.
"""

from ath_contracts import Persona

DEFAULT_AVATAR_ID = "avatar-aith"

# Vincent — мужской мультяшный персонаж, голос сценария ему не подходит по
# той же причине, что и Tom'у. Общий с Tom'ом «Daniel» — осознанно: отдельный
# мужской голос под него не подбирали, а звучать голосом Ирины он не должен.
_VOICES: dict[str, str] = {"tom-avatar": "Daniel", "vincent-avatar": "Daniel"}

DEFAULT_RECOVERY_LINE = "Простите, вас плохо слышно. Повторите, пожалуйста."
"""Формулировка по умолчанию.

Без прошедшего времени намеренно: «не расслышал» и «не расслышала» разошлись бы
по роду персонажа, а настоящее время одинаково годится всем. Вина не
перекладывается на собеседника, и прямо запрошен повтор.
"""

# Vincent'у своей строки НЕ заводим намеренно: DEFAULT_RECOVERY_LINE нейтральна
# и годится обычному человекоподобному персонажу. Отдельная строка нужна была
# Tom'у именно потому, что он кот, — «Простите, вас плохо слышно» из кошачьей
# морды звучит нелепо. У Vincent'а такой проблемы нет.
_RECOVERY_LINES: dict[str, str] = {"tom-avatar": "Мур? Не расслышал. Повтори-ка."}


def voice_for(avatar_id: str, persona: Persona) -> str | None:
    """Голос профиля; для основного аватара — голос персонажа сценария."""
    return _VOICES.get(avatar_id) or persona.voice_id


def recovery_line_for(avatar_id: str) -> str:
    return _RECOVERY_LINES.get(avatar_id, DEFAULT_RECOVERY_LINE)


def known_profiles() -> list[tuple[str, str]]:
    """Пары «id профиля → фраза восстановления» для предрендера."""
    ids = {DEFAULT_AVATAR_ID, *_VOICES, *_RECOVERY_LINES}
    return sorted((avatar_id, recovery_line_for(avatar_id)) for avatar_id in ids)
