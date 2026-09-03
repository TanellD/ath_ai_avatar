#!/usr/bin/env python3
"""Gantt-график операций конвейера для одной сессии — офлайн, без веб-админки.

Тянет те же данные, что и /admin/sessions/<id> в браузере (см.
services/gateway/app/api/admin.py), но рисует все ходы («сообщения»,
gen_id) сессии сразу, один под другим, в один файл — удобно для архива
конкретного прогона или разбора конкретного бага без поднятого фронтенда.

Один спан — один горизонтальный бар. Вложенность видна напрямую: пока
конвейер последовательный (см. TODO в pipeline.py), tts_synthesize лежит
внутри character_reply по времени, и это на графике так и выглядит —
бары на разных строках перекрываются по X. Если/когда TTS для предложения
N станет распараллелен с чтением токенов N+1, здесь ничего менять не
придётся: перекрывающиеся бары на разных строках — это и есть
параллелизм, ровно то же представление.

Использование:
    pip install matplotlib
    python scripts/session_gantt.py <session_id> [--api-url http://localhost:8000] [--out FILE.png] [--show]

Без --show только сохраняет PNG и печатает сводку по каждому ходу в
терминал (без matplotlib текстовая сводка всё равно доступна через --no-plot).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

OPERATION_COLOR = {
    "character_reply": "#4f7cff",
    "tts_synthesize": "#31b58c",
    "classify": "#c98a2c",
}
FALLBACK_COLOR = "#8b8fa3"


@dataclass
class Span:
    seq: int
    operation: str
    label: str
    start_ms: int
    end_ms: int
    status: str
    error: str | None


@dataclass
class Gen:
    gen_id: int
    preview: str
    spans: list[Span]


def _fetch(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.load(response)
    except urllib.error.URLError as exc:
        print(f"Не удалось обратиться к {url}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def load_session(api_url: str, session_id: str) -> list[Gen]:
    gens_data = _fetch(f"{api_url}/admin/sessions/{session_id}/gens")["items"]
    result: list[Gen] = []
    for g in gens_data:
        spans_data = _fetch(
            f"{api_url}/admin/sessions/{session_id}/gens/{g['gen_id']}/spans"
        )["items"]
        spans = [
            Span(
                seq=s["seq"],
                operation=s["operation"],
                label=s["label"],
                start_ms=s["start_ms"],
                end_ms=s["end_ms"],
                status=s["status"],
                error=s["error"],
            )
            for s in spans_data
        ]
        result.append(Gen(gen_id=g["gen_id"], preview=g["preview"], spans=spans))
    return result


def print_summary(gens: list[Gen]) -> None:
    for gen in gens:
        total_ms = max((s.end_ms for s in gen.spans), default=0)
        print(f"\n=== Сообщение #{gen.gen_id}: {gen.preview!r} ({total_ms} мс) ===")
        for s in gen.spans:
            flag = "" if s.status == "ok" else f"  [{s.status}]"
            print(f"  #{s.seq:<2} {s.operation:<18} {s.end_ms - s.start_ms:>5} мс  {s.label[:60]}{flag}")


def plot(gens: list[Gen], out_path: str, show: bool) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib не установлен — пропускаю график (pip install matplotlib).", file=sys.stderr)
        return

    gens_with_spans = [g for g in gens if g.spans]
    if not gens_with_spans:
        print("Нет спанов ни в одном ходе сессии — рисовать нечего.", file=sys.stderr)
        return

    fig, axes = plt.subplots(
        len(gens_with_spans), 1, figsize=(11, 2 + 1.1 * sum(len(g.spans) for g in gens_with_spans)),
        squeeze=False,
    )

    for ax_row, gen in zip(axes, gens_with_spans, strict=True):
        ax = ax_row[0]
        for row_i, span in enumerate(gen.spans):
            color = OPERATION_COLOR.get(span.operation, FALLBACK_COLOR)
            edge = {"ok": "none", "error": "red", "cancelled": "#555"}.get(span.status, "none")
            linestyle = "dashed" if span.status == "cancelled" else "solid"
            ax.broken_barh(
                [(span.start_ms, max(span.end_ms - span.start_ms, 1))],
                (row_i - 0.4, 0.8),
                facecolors=color,
                edgecolors=edge,
                linewidth=2,
                linestyle=linestyle,
            )
            ax.text(
                span.start_ms + 5, row_i, span.label[:40],
                va="center", fontsize=8, color="white", clip_on=True,
            )

        ax.set_yticks(range(len(gen.spans)))
        ax.set_yticklabels([f"#{s.seq} {s.operation}" for s in gen.spans], fontsize=8)
        ax.set_xlabel("мс от начала хода")
        ax.set_title(f"Сообщение #{gen.gen_id}: {gen.preview[:70]}", fontsize=10, loc="left")
        ax.invert_yaxis()
        ax.grid(axis="x", linestyle=":", alpha=0.4)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"\nСохранено: {out_path}")
    if show:
        plt.show()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("session_id", help="id сессии (см. /admin/sessions в веб-панели)")
    parser.add_argument("--api-url", default="http://localhost:8000", help="адрес gateway")
    parser.add_argument("--out", default=None, help="путь к PNG (по умолчанию session_<id>_gantt.png)")
    parser.add_argument("--show", action="store_true", help="открыть график в окне после сохранения")
    parser.add_argument("--no-plot", action="store_true", help="только текстовая сводка, без matplotlib")
    args = parser.parse_args()

    gens = load_session(args.api_url, args.session_id)
    if not gens:
        print("У этой сессии пока нет ни одного хода сотрудника.", file=sys.stderr)
        raise SystemExit(1)

    print_summary(gens)

    if not args.no_plot:
        out_path = args.out or f"session_{args.session_id[:8]}_gantt.png"
        plot(gens, out_path, args.show)


if __name__ == "__main__":
    main()
