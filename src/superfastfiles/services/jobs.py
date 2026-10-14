"""Fila de tarefas e histórico (JSON na pasta de dados). A interface não grava arquivos direto: usa isto."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from superfastfiles.core.paths import DATA_DIR
from superfastfiles.engine.job import JobSpec, MODE_LABELS, Mode

HISTORY_FILE = DATA_DIR / "historico.json"
QUEUE_FILE = DATA_DIR / "fila.json"
HISTORY_MAX = 300
_lock = threading.Lock()


def describe(spec: JobSpec) -> str:
    src = spec.sources[0] if spec.sources else "—"
    more = f" (+{len(spec.sources) - 1})" if len(spec.sources) > 1 else ""
    if spec.mode == Mode.DELETE:
        return f"{MODE_LABELS[spec.mode]}: {src}{more}"
    return f"{MODE_LABELS[spec.mode]}: {src}{more} → {spec.dest}"


@dataclass
class HistoryItem:
    when: float
    mode: str
    sources: list[str]
    dest: str
    files: int
    bytes: int
    skipped: int
    deleted: int
    errors: int
    seconds: float
    verified: bool
    cancelled: bool = False
    dry_run: bool = False
    strategy: str = ""
    error_lines: list[str] = field(default_factory=list)

    @property
    def speed(self) -> float:
        return self.bytes / self.seconds if self.seconds > 0 else 0.0


def _load(path: Path) -> list:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(path: Path, data: list) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(path)


# Histórico ---------------------------------------------------------------------
def history() -> list[HistoryItem]:
    known = HistoryItem.__dataclass_fields__
    return [HistoryItem(**{k: v for k, v in d.items() if k in known}) for d in _load(HISTORY_FILE)]


def add_history(spec: JobSpec, snap: dict, cancelled: bool, errors: list) -> HistoryItem:
    item = HistoryItem(when=time.time(), mode=str(spec.mode), sources=list(spec.sources), dest=spec.dest,
                       files=snap["done_files"], bytes=snap["done_bytes"], skipped=snap["skipped_files"],
                       deleted=snap["deleted_files"], errors=snap["errors"], seconds=snap["elapsed"],
                       verified=spec.verify, cancelled=cancelled, dry_run=spec.dry_run, strategy=snap["strategy"],
                       error_lines=[f"{e.path}: {e.message}" for e in errors[:200]])
    with _lock:
        data = _load(HISTORY_FILE)
        data.insert(0, asdict(item))
        _save(HISTORY_FILE, data[:HISTORY_MAX])
    return item


def clear_history() -> None:
    with _lock:
        _save(HISTORY_FILE, [])


# Fila -------------------------------------------------------------------------
def queue() -> list[JobSpec]:
    return [JobSpec.from_json(json.dumps(d)) for d in _load(QUEUE_FILE)]


def set_queue(specs: list[JobSpec]) -> None:
    with _lock:
        _save(QUEUE_FILE, [json.loads(s.to_json()) for s in specs])


def enqueue(spec: JobSpec) -> int:
    q = queue()
    q.append(spec)
    set_queue(q)
    return len(q)


def pop_queue() -> JobSpec | None:
    q = queue()
    if not q:
        return None
    first = q.pop(0)
    set_queue(q)
    return first
