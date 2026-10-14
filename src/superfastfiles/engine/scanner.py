"""Varredura paralela das origens, com filtros.

Várias threads chamam `os.scandir` ao mesmo tempo (a chamada solta o GIL), o que acelera muito pastas com milhares
de arquivos, principalmente em rede. As entradas saem por uma fila enquanto a varredura continua: a cópia começa
antes de a varredura terminar.

Ordem garantida: uma pasta sempre sai na fila antes de qualquer coisa de dentro dela.
"""
from __future__ import annotations

import fnmatch
import os
import queue
import stat as st
import sys
import threading
from dataclasses import dataclass, field

WIN = sys.platform == "win32"


@dataclass(slots=True)
class Entry:
    kind: str           # "file" | "dir" | "link"
    src: str            # caminho completo na origem
    rel: str            # caminho relativo dentro do destino (usa os.sep)
    size: int = 0
    mtime_ns: int = 0
    atime_ns: int = 0
    mode: int = 0


@dataclass(slots=True)
class DirListing:
    """Fim da varredura de uma pasta: nomes que existem na origem (para o Sincronizar saber o que apagar)."""
    rel: str
    names: set = field(default_factory=set)


DONE = object()


class Filters:
    def __init__(self, include=(), exclude=(), min_size=0, max_size=0, newer_than=0.0, older_than=0.0):
        norm = (lambda p: p.lower()) if WIN else (lambda p: p)
        self._norm = norm
        self.include = [norm(p.replace("\\", "/")) for p in include if p.strip()]
        self.exclude = [norm(p.replace("\\", "/")) for p in exclude if p.strip()]
        self.min_size, self.max_size = min_size, max_size
        self.newer_ns = int(newer_than * 1e9) if newer_than else 0
        self.older_ns = int(older_than * 1e9) if older_than else 0

    @staticmethod
    def _match(patterns, name: str, rel: str) -> bool:
        for p in patterns:
            if "/" in p:
                if fnmatch.fnmatchcase(rel, p.strip("/")) or fnmatch.fnmatchcase(rel, "*/" + p.strip("/")):
                    return True
            elif fnmatch.fnmatchcase(name, p):
                return True
        return False

    def dir_ok(self, name: str, rel: str) -> bool:
        if not self.exclude:
            return True
        n = self._norm(name)
        r = self._norm(rel.replace(os.sep, "/"))
        return not self._match(self.exclude, n, r)

    def file_ok(self, name: str, rel: str, size: int, mtime_ns: int) -> bool:
        n = self._norm(name)
        r = self._norm(rel.replace(os.sep, "/"))
        if self.exclude and self._match(self.exclude, n, r):
            return False
        if self.include and not self._match(self.include, n, r):
            return False
        if self.min_size and size < self.min_size:
            return False
        if self.max_size and size > self.max_size:
            return False
        if self.newer_ns and mtime_ns < self.newer_ns:
            return False
        if self.older_ns and mtime_ns > self.older_ns:
            return False
        return True

    @property
    def active(self) -> bool:
        return bool(self.include or self.exclude or self.min_size or self.max_size or self.newer_ns or self.older_ns)


def _entry_from(de: os.DirEntry, rel: str) -> Entry | None:
    try:
        if de.is_symlink() or (WIN and de.is_junction()):
            return Entry("link", de.path, rel)
        s = de.stat(follow_symlinks=False)
    except OSError:
        return None
    if st.S_ISDIR(s.st_mode):
        return Entry("dir", de.path, rel, 0, s.st_mtime_ns, s.st_atime_ns, s.st_mode)
    if st.S_ISREG(s.st_mode):
        return Entry("file", de.path, rel, s.st_size, s.st_mtime_ns, s.st_atime_ns, s.st_mode)
    return None      # sockets, dispositivos etc.


class Scanner:
    """Produz Entry / DirListing / DONE na fila `out`. Erros vão para `on_error(path, msg)`."""

    def __init__(self, roots: list[tuple[str, str]], filters: Filters, out: queue.Queue, on_error,
                 threads: int = 8, want_listings: bool = False, cancel: threading.Event | None = None):
        self.roots = roots              # (caminho de origem, prefixo relativo no destino)
        self.filters = filters
        self.out = out
        self.on_error = on_error
        self.threads = max(1, threads)
        self.want_listings = want_listings
        self.cancel = cancel or threading.Event()
        self._work: queue.Queue = queue.Queue()
        self._pending = 0
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    def start(self):
        dirs = []
        for src, rel in self.roots:
            try:
                s = os.stat(src, follow_symlinks=True)
            except OSError as e:
                self.on_error(src, e.strerror or str(e))
                continue
            if st.S_ISDIR(s.st_mode):
                if rel:     # a própria pasta vira uma pasta no destino
                    self.out.put(Entry("dir", src, rel, 0, s.st_mtime_ns, s.st_atime_ns, s.st_mode))
                dirs.append((src, rel))
            else:
                name = os.path.basename(src)
                if self.filters.file_ok(name, rel, s.st_size, s.st_mtime_ns):
                    self.out.put(Entry("file", src, rel, s.st_size, s.st_mtime_ns, s.st_atime_ns, s.st_mode))
        if not dirs:
            self.out.put(DONE)
            return
        self._pending = len(dirs)
        for d in dirs:
            self._work.put(d)
        for i in range(self.threads):
            t = threading.Thread(target=self._worker, name=f"scan-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def _worker(self):
        while True:
            item = self._work.get()
            if item is None:
                return
            path, rel = item
            try:
                if not self.cancel.is_set():
                    self._scan_dir(path, rel)
            except Exception as e:          # noqa: BLE001 — erro numa pasta não para a varredura
                self.on_error(path, str(e))
            with self._lock:
                self._pending -= 1
                last = self._pending == 0
            if last:
                for _ in self._threads:
                    self._work.put(None)
                self.out.put(DONE)

    def _scan_dir(self, path: str, rel: str):
        f = self.filters
        names = set() if self.want_listings else None
        subdirs = []
        try:
            it = os.scandir(path)
        except OSError as e:
            self.on_error(path, e.strerror or str(e))
            return
        with it:
            for de in it:
                child_rel = os.path.join(rel, de.name) if rel else de.name
                if names is not None:
                    names.add(de.name.lower() if WIN else de.name)
                e = _entry_from(de, child_rel)
                if e is None:
                    continue
                if e.kind == "dir":
                    if f.dir_ok(de.name, child_rel):
                        self.out.put(e)
                        subdirs.append((e.src, child_rel))
                elif e.kind == "file":
                    if f.file_ok(de.name, child_rel, e.size, e.mtime_ns):
                        self.out.put(e)
                else:
                    if f.dir_ok(de.name, child_rel):
                        self.out.put(e)
        if names is not None:
            self.out.put(DirListing(rel, names))
        if subdirs:
            with self._lock:
                self._pending += len(subdirs)
            for d in subdirs:
                self._work.put(d)
