"""The dev log: one JSON line per Answer in `database/ask_log.jsonl` (gitignored, questions may hold client data)."""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path


class AskLog:
    """Appends `{timestamp, model, **record}` as one JSON line. A write failure only warns."""

    def __init__(self, path: Path, model: str = ""):
        self._path = path
        self._model = model

    def write(self, record: dict) -> None:
        line = {"timestamp": datetime.now(timezone.utc).isoformat(), "model": self._model, **record}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError as error:
            warnings.warn(f"could not write the ask log {self._path}: {error}")
