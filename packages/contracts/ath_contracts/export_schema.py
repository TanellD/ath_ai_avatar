"""Экспорт JSON Schema контрактов → генерация TypeScript-типов для фронтенда.

    python -m ath_contracts.export_schema --out services/frontend/src/contracts/schema.json

Дальше `npm run gen:contracts` во фронтенде превращает схему в .d.ts. Смысл в
том, чтобы у браузера и сервера не было двух рукописных представлений одного
контракта — рассинхрон здесь молча ломает фильтрацию по gen_id.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from ath_contracts.events import ClientEvent, ServerEvent
from ath_contracts.report import Report
from ath_contracts.scenario import Scenario
from ath_contracts.session import SessionState

_EXPORTED: dict[str, Any] = {
    "ClientEvent": ClientEvent,
    "ServerEvent": ServerEvent,
    "Scenario": Scenario,
    "SessionState": SessionState,
    "Report": Report,
}


def build_schema() -> dict[str, Any]:
    """Собирает единый JSON Schema документ со всеми экспортируемыми моделями."""
    definitions: dict[str, Any] = {}
    properties: dict[str, Any] = {}

    for name, model in _EXPORTED.items():
        schema = TypeAdapter(model).json_schema(ref_template="#/$defs/{model}")
        definitions.update(schema.pop("$defs", {}))
        definitions[name] = schema
        properties[name] = {"$ref": f"#/$defs/{name}"}

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AthContracts",
        "type": "object",
        "properties": properties,
        "$defs": definitions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Путь к выходному .json")
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(build_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"schema written to {args.out}")


if __name__ == "__main__":
    main()
