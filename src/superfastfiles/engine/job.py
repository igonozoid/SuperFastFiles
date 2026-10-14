"""Descrição de uma tarefa (JobSpec) e contadores de andamento (JobStats).

O motor não depende do Qt: a CLI e a interface usam as mesmas classes.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import StrEnum

from superfastfiles.i18n import tr


class Mode(StrEnum):
    COPY = "copy"          # copiar (não apaga nada no destino)
    MOVE = "move"          # copiar e apagar a origem
    SYNC = "sync"          # copiar e apagar no destino o que não existe mais na origem
    DELETE = "delete"      # apagar as origens


class Overwrite(StrEnum):
    DIFF = "diff"          # só quando tamanho ou data forem diferentes (padrão)
    NEWER = "newer"        # só quando a origem for mais nova
    ALWAYS = "always"      # sempre sobrescrever
    NEVER = "never"        # nunca sobrescrever


def mode_label(m: Mode | str) -> str:
    return {Mode.COPY: tr("Copiar"), Mode.MOVE: tr("Mover"), Mode.SYNC: tr("Sincronizar"),
            Mode.DELETE: tr("Apagar")}[Mode(m)]


def overwrite_label(o: Overwrite | str) -> str:
    return {Overwrite.DIFF: tr("Só os diferentes (tamanho/data)"), Overwrite.NEWER: tr("Só se a origem for mais nova"),
            Overwrite.ALWAYS: tr("Sempre sobrescrever"), Overwrite.NEVER: tr("Nunca sobrescrever")}[Overwrite(o)]


# Ações da simulação: código estável no motor, texto traduzido só na hora de mostrar
def action_label(code: str) -> str:
    return {"copy": tr("copiar"), "overwrite": tr("sobrescrever"), "skip": tr("pular"), "delete": tr("apagar"),
            "mkdir": tr("criar pasta"), "rmdir": tr("apagar pasta"), "link": tr("link")}.get(code, code)


@dataclass
class JobSpec:
    mode: Mode = Mode.COPY
    sources: list[str] = field(default_factory=list)
    dest: str = ""
    overwrite: Overwrite = Overwrite.DIFF
    verify: bool = False
    include: list[str] = field(default_factory=list)    # padrões glob ("*.jpg"); vazio = tudo
    exclude: list[str] = field(default_factory=list)    # padrões glob para arquivos e pastas
    min_size: int = 0                                   # bytes; 0 = sem limite
    max_size: int = 0
    newer_than: float = 0.0                             # timestamp; 0 = sem limite
    older_than: float = 0.0
    preserve_times: bool = True
    dry_run: bool = False                               # simulação: só lista o que seria feito
    threads: int = 0                                    # 0 = automático (conforme os discos)
    buffer_mb: int = 0                                  # 0 = automático
    disk_mode: str = "auto"                             # auto | ssd | hdd | same (mesmo disco)
    unbuffered: bool = True                             # E/S sem cache do sistema nos arquivos grandes
    native: bool = True                                 # usar a cópia nativa do SO quando não há verificação

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "JobSpec":
        d = json.loads(text)
        d["mode"] = Mode(d.get("mode", "copy"))
        d["overwrite"] = Overwrite(d.get("overwrite", "diff"))
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class FileError:
    path: str
    message: str
    when: float = field(default_factory=time.time)


class JobStats:
    """Contadores compartilhados entre as threads do motor. A interface lê `snapshot()` (~10x por segundo)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.scan_files = 0          # arquivos encontrados que serão processados
        self.scan_bytes = 0
        self.scanning = True
        self.done_files = 0
        self.done_bytes = 0          # bytes efetivamente copiados (inclui parciais de arquivos em andamento)
        self.verified_files = 0
        self.skipped_files = 0       # iguais no destino (não precisavam de cópia)
        self.skipped_bytes = 0
        self.deleted_files = 0
        self.deleted_dirs = 0
        self.dirs_created = 0
        self.errors: list[FileError] = []
        self.current = ""
        self.started = time.monotonic()
        self.finished: float | None = None
        self.strategy = ""
        self.log: deque[str] = deque(maxlen=5000)

    # Chamado pelas threads -------------------------------------------------
    def add(self, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, getattr(self, k) + v)

    def bytes_done(self, n: int):
        with self._lock:
            self.done_bytes += n

    def error(self, path: str, message: str):
        with self._lock:
            self.errors.append(FileError(path, message))
            self.log.append(tr("ERRO  {path}: {message}", path=path, message=message))

    def note(self, line: str):
        with self._lock:
            self.log.append(line)

    # Leitura ----------------------------------------------------------------
    @property
    def elapsed(self) -> float:
        return (self.finished or time.monotonic()) - self.started

    def snapshot(self) -> dict:
        with self._lock:
            return dict(scan_files=self.scan_files, scan_bytes=self.scan_bytes, scanning=self.scanning,
                        done_files=self.done_files, done_bytes=self.done_bytes, verified_files=self.verified_files,
                        skipped_files=self.skipped_files, skipped_bytes=self.skipped_bytes,
                        deleted_files=self.deleted_files, deleted_dirs=self.deleted_dirs,
                        dirs_created=self.dirs_created, errors=len(self.errors), current=self.current,
                        elapsed=self.elapsed, finished=self.finished is not None, strategy=self.strategy)


@dataclass
class PlanItem:
    """Uma ação da simulação (dry-run)."""
    action: str        # copy | overwrite | skip | delete | mkdir | rmdir | link (texto: action_label)
    path: str
    size: int = 0
