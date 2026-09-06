"""Полные прогоны: довести диалог до завершения, оценки и отчёта.

Чем отличается от прошлого стенда. Тот слал фиксированный список из 4-5 реплик
и по построению не мог дойти до конца: objection_price требует до 18 ходов по
четырём этапам, interview_junior — до 12 по трём. Здесь реплика выбирается
ПО ТЕКУЩЕМУ ЭТАПУ, который приходит в событии `action`, а не по номеру хода.
Автомат ведёт сценарий, стенд за ним следует — иначе критерии этапов
(«выяснил поставщика, объём и что не устраивает») не зачитываются и переход
происходит по max_turns, то есть сценарий «проходит» не по-настоящему.

Меряет заодно метрику 4 (§9) — возвраты отменённого хвоста, — которую
браузерный стенд снять не мог: для неё нужен gen_id пришедших чанков.

И проверяет главную гипотезу §7: под каждым баллом обязана быть дословная
цитата из реплики сотрудника. Не «поле заполнено», а именно дословность —
цитата ищется в транскрипте.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field

import httpx
import websockets

# Умолчания — под запуск ВНУТРИ контейнера gateway (см. README): там нужный
# websockets уже стоит, а localhost:8000 — сам шлюз. С хоста переопределяются
# переменными окружения.
API = os.environ.get("ACCEPTANCE_API", "http://localhost:8000")
WS = os.environ.get("ACCEPTANCE_WS", "ws://localhost:8000")
AVATAR = os.environ.get("ACCEPTANCE_AVATAR", "avatar-aith")
OUT = os.environ.get("ACCEPTANCE_OUT", "/data/full_runs.jsonl")
RUNS = int(os.environ.get("ACCEPTANCE_RUNS", "5"))

MAX_TURNS = 26          # предохранитель: сценарию хватает 18
IDLE_SEC = 6.0          # тишина, означающая «персонаж договорил»
FIRST_EVENT_SEC = 60.0  # до первого события успевают LLM и первый чанк TTS
TURN_BUDGET_SEC = 150.0
REPORT_BUDGET_SEC = 240.0  # оценка идёт сильной моделью, таймаут у неё 120 с

# Реплики по этапам. Написаны под completion_criteria каждого этапа: если
# отвечать не по делу, классификатор вернёт incomplete и разговор упрётся
# в max_turns вместо честного перехода.
REPLIES: dict[str, dict[str, list[str]]] = {
    "objection_price": {
        "opening": [
            "Здравствуйте, Ирина! Меня зовут Пётр, компания «Ортекс», я занимаюсь "
            "поставками по вашей категории. Спасибо, что нашли время. Расскажите, "
            "пожалуйста, как у вас сейчас устроены закупки по этой позиции?",
            "Понял вас. А кто ещё со стороны компании участвует в решении по таким "
            "поставкам?",
        ],
        "discovery": [
            "А с кем вы сейчас работаете по этой позиции — кто у вас основной поставщик?",
            "Какой объём вы берёте у них в месяц?",
            "А что в работе с ними устраивает меньше всего — сроки, качество или "
            "что-то другое?",
            "Понял. И как часто из-за этого приходится решать вопросы в ручном режиме?",
        ],
        "objection": [
            "Дорого относительно чего, если сравнивать не строчку в счёте, а итог за "
            "год? Вы сами сказали, что срывы сроков приходится закрывать вручную — "
            "у нас замена и подстраховка уже входят в цену.",
            "Скидку я сейчас предлагать не буду, это было бы нечестно по отношению "
            "к вам же. Давайте посчитаем: доставка за наш счёт и замена брака без "
            "экспертизы у текущего поставщика — это отдельные деньги.",
            "Давайте посчитаем на том объёме, который вы назвали: сравним не цену за "
            "единицу, а сумму за год со всеми доплатами. Если у нас выйдет дороже — "
            "я первый это скажу.",
        ],
        "closing": [
            "Давайте так: я пришлю расчёт на ваш объём до пятницы, а в понедельник в "
            "одиннадцать созвонимся на пятнадцать минут и обсудим цифры. Годится?",
            "Отлично, тогда до понедельника, в одиннадцать. Спасибо за время!",
        ],
    },
    "interview_junior": {
        "opening": [
            "Здравствуйте, Павел! Меня зовут Пётр, я тимлид команды. Формат такой: "
            "минут сорок поговорим про ваш опыт, потом вы зададите свои вопросы. "
            "Расскажите для начала, над чем работали последнее время?",
            "Спасибо. А что в этой работе нравилось больше всего?",
        ],
        "experience": [
            "Возьмём последний проект — какую именно часть делали вы сами, а что было "
            "на других участниках?",
            "Расскажите подробнее про ту часть, что писали вы: какие решения принимали "
            "сами, а где спрашивали совета?",
            "Что там оказалось самым сложным лично для вас, и как вы это решили?",
            "Если бы делали ту же задачу заново — что сделали бы иначе?",
        ],
        "closing": [
            "Спасибо, картина понятная. Мы вернёмся с ответом до конца недели: в "
            "пятницу напишу в любом случае. А сейчас — какие у вас есть вопросы ко мне?",
            "Хороший вопрос. Ещё что-то хотите уточнить?",
            "Тогда спасибо, что пришли. До связи в пятницу!",
        ],
    },
}


@dataclass
class Turn:
    index: int
    stage: str
    sent_at: float
    text: str
    first_token_ms: float | None = None
    first_audio_ms: float | None = None
    audio_chunks: int = 0


@dataclass
class Run:
    label: str
    scenario_id: str
    session_id: str = ""
    turns: list[Turn] = field(default_factory=list)
    stages_seen: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    stale_chunks: int = 0
    cancels: int = 0
    finished: bool = False
    report: dict | None = None
    opening_first_audio_ms: float | None = None
    duration_sec: float = 0.0


class Client:
    def __init__(self, run: Run, ws, opening_started: float) -> None:  # noqa: ANN001
        self.run = run
        self.ws = ws
        self.turn: Turn | None = None
        self.current_stage = ""
        self.cancelled_gens: set[int] = set()
        self.opening_started = opening_started

    async def pump(self, budget_sec: float, idle_sec: float = IDLE_SEC) -> bool:
        """Читает до тишины или до конца бюджета. True — сессия завершилась."""
        started = last = time.perf_counter()
        deadline = started + budget_sec
        seen = False
        while time.perf_counter() < deadline:
            gap = idle_sec if seen else FIRST_EVENT_SEC
            base = last if seen else started
            try:
                raw = await asyncio.wait_for(
                    self.ws.recv(), timeout=max(0.05, min(gap - (time.perf_counter() - base), 5.0))
                )
            except TimeoutError:
                if time.perf_counter() - base >= gap:
                    if not seen:
                        self.run.issues.append(
                            f"ни одного события за {FIRST_EVENT_SEC:.0f} с после отправки"
                        )
                    return False
                continue
            except websockets.ConnectionClosed:
                self.run.issues.append("сокет закрыт сервером посреди хода")
                return False
            seen = True
            last = time.perf_counter()
            if self.handle(json.loads(raw)):
                return True
        return False

    def handle(self, ev: dict) -> bool:
        kind = ev.get("type")
        gen = ev.get("gen_id")
        now = time.perf_counter()

        # Метрика 4 — жёсткий инвариант: ни одного чанка отменённого поколения.
        if kind == "audio_chunk" and gen in self.cancelled_gens:
            self.run.stale_chunks += 1

        if kind == "cancel":
            self.run.cancels += 1
            if isinstance(gen, int):
                self.cancelled_gens.add(gen)
            return False

        if kind == "token":
            if self.turn and self.turn.first_token_ms is None:
                self.turn.first_token_ms = (now - self.turn.sent_at) * 1000
        elif kind == "audio_chunk":
            if self.turn is not None:
                self.turn.audio_chunks += 1
                if self.turn.first_audio_ms is None:
                    self.turn.first_audio_ms = (now - self.turn.sent_at) * 1000
            elif self.run.opening_first_audio_ms is None:
                self.run.opening_first_audio_ms = (now - self.opening_started) * 1000
        elif kind == "action":
            action = ev.get("action", "?")
            self.run.actions.append(action)
            stage = ev.get("stage_id")
            if stage:
                self.current_stage = stage
                if not self.run.stages_seen or self.run.stages_seen[-1] != stage:
                    self.run.stages_seen.append(stage)
            if action in {"finish", "evaluate"}:
                self.run.finished = True
        elif kind == "error":
            self.run.errors.append({k: ev.get(k) for k in ("code", "message")})
        elif kind == "report":
            self.run.report = ev.get("report")
            return True
        return False

    async def say(self, text: str) -> None:
        turn = Turn(
            index=len(self.run.turns) + 1,
            stage=self.current_stage,
            sent_at=time.perf_counter(),
            text=text,
        )
        self.run.turns.append(turn)
        self.turn = turn
        await self.ws.send(
            json.dumps(
                {"type": "user_message", "text": text, "interrupts": None, "avatar_id": AVATAR}
            )
        )


def pick_reply(scenario_id: str, stage: str, used: dict[str, int]) -> str:
    pools = REPLIES[scenario_id]
    pool = pools.get(stage) or next(iter(pools.values()))
    n = used.get(stage, 0)
    used[stage] = n + 1
    return pool[min(n, len(pool) - 1)] if n < len(pool) else pool[n % len(pool)]


def check_evidence(report: dict) -> list[str]:
    """Каждый балл обязан нести дословную цитату из реплики сотрудника (§7).

    Проверяем не «поле не пустое», а именно дословность: без неё методист не
    сможет свериться за десять секунд, и главная гипотеза продукта рушится.
    """
    problems: list[str] = []
    said = " ".join(
        t.get("text", "") for t in report.get("transcript", []) if t.get("role") == "user"
    )
    normalised = " ".join(said.split()).replace("«", '"').replace("»", '"')
    for score in report.get("scores", []):
        cid = score.get("criterion_id", "?")
        quote = (score.get("evidence") or "").strip()
        if not quote:
            problems.append(f"{cid}: цитаты нет вовсе")
            continue
        needle = " ".join(quote.split()).strip('"«» ').replace("«", '"').replace("»", '"')
        if needle and needle not in normalised:
            problems.append(f"{cid}: цитата не найдена в транскрипте дословно — {needle[:60]!r}")
    return problems


async def run_one(label: str, scenario_id: str) -> Run:
    run = Run(label=label, scenario_id=scenario_id)
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient() as http:
            r = await http.post(
                f"{API}/sessions", json={"scenario_id": scenario_id}, timeout=180
            )
            r.raise_for_status()
            body = r.json()
        run.session_id = body["session_id"]

        async with websockets.connect(
            f"{WS}/ws/session/{run.session_id}", max_size=None, ping_interval=20
        ) as ws:
            client = Client(run, ws, opening_started=time.perf_counter())
            client.current_stage = body["scenario"]["stages"][0]["id"]
            run.stages_seen.append(client.current_stage)

            # Открывающая реплика: инициативу держит агент (§1).
            await client.pump(TURN_BUDGET_SEC)

            used: dict[str, int] = {}
            while not run.finished and len(run.turns) < MAX_TURNS:
                reply = pick_reply(scenario_id, client.current_stage, used)
                await client.say(reply)
                if await client.pump(TURN_BUDGET_SEC):
                    break

            if run.finished and run.report is None:
                await client.pump(REPORT_BUDGET_SEC, idle_sec=REPORT_BUDGET_SEC)

            if not run.finished:
                run.issues.append(
                    f"сценарий не завершился за {len(run.turns)} ходов (предел {MAX_TURNS})"
                )
    except Exception as exc:  # noqa: BLE001 — стенд обязан пережить любой сбой
        run.issues.append(f"{type(exc).__name__}: {exc}"[:200])
    run.duration_sec = time.perf_counter() - started
    return run


PLAN = [
    ("1  дорого", "objection_price"),
    ("2  собеседование", "interview_junior"),
    ("3  дорого", "objection_price"),
    ("4  собеседование", "interview_junior"),
    ("5  дорого", "objection_price"),
]


async def main() -> int:
    only = os.environ.get("ACCEPTANCE_SCENARIO", "")
    plan = [item for item in PLAN if not only or item[1] == only][:RUNS]
    open(OUT, "w").close()
    for label, scenario_id in plan:
        run = await run_one(label, scenario_id)
        report = run.report or {}
        evidence_problems = check_evidence(report) if report else ["отчёта нет"]
        record = {
            "label": label,
            "scenario_id": scenario_id,
            "session_id": run.session_id,
            "turns": len(run.turns),
            "stages_seen": run.stages_seen,
            "actions": run.actions,
            "finished": run.finished,
            "has_report": bool(report),
            "total_score": report.get("total_score"),
            "scores": len(report.get("scores", [])),
            "stages_completed": report.get("stages_completed"),
            "stages_total": report.get("stages_total"),
            "verdict": (report.get("verdict") or "")[:160],
            "evidence_problems": evidence_problems,
            "stale_chunks": run.stale_chunks,
            "cancels": run.cancels,
            "errors": run.errors,
            "issues": run.issues,
            "duration_sec": round(run.duration_sec, 1),
            "opening_first_audio_ms": (
                round(run.opening_first_audio_ms) if run.opening_first_audio_ms else None
            ),
            "first_audio_ms": [
                round(t.first_audio_ms) if t.first_audio_ms else None for t in run.turns
            ],
            "turn_stages": [t.stage for t in run.turns],
        }
        with open(OUT, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(
            f"{label:<18} ходов {len(run.turns):>2} | этапы {'>'.join(run.stages_seen)} | "
            f"завершён {'да' if run.finished else 'НЕТ'} | отчёт {'да' if report else 'НЕТ'} | "
            f"балл {report.get('total_score')} | цитаты "
            f"{'ок' if not evidence_problems else 'ПРОБЛЕМЫ ' + str(len(evidence_problems))} | "
            f"хвост {run.stale_chunks} | {run.duration_sec:.0f} с"
            + (f" | {run.issues[0]}" if run.issues else ""),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
