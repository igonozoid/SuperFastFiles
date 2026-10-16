"""Orquestra uma tarefa: varredura -> decisão por arquivo -> threads de cópia -> pós (sincronizar/mover/datas).

Uso (CLI, interface e testes):
    r = Runner(spec)
    r.run()                 # bloqueia; de outra thread: r.pause(), r.resume(), r.cancel()
    r.stats.snapshot()
"""
from __future__ import annotations

import os
import queue
import shutil
import stat as st
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from superfastfiles.engine import extras, metadata
from superfastfiles.engine.copier_base import Cancelled, Copier, CopyContext, FileIO
from superfastfiles.engine.disk import choose_strategy, disk_info
from superfastfiles.engine.job import JobSpec, JobStats, Mode, Overwrite, PlanItem
from superfastfiles.engine.metadata import display_path, long_path
from superfastfiles.engine.scanner import DONE, DirListing, Entry, Filters, Scanner
from superfastfiles.engine.verify import VerifyError
from superfastfiles.i18n import tr

WIN = sys.platform == "win32"
LARGE = 8 << 20                    # a partir daqui o arquivo vai para a fila de "grandes" (pipeline)
TIME_TOLERANCE_NS = 2_000_000_000  # FAT/exFAT guardam a data com até 2 s de diferença
_LAZY = object()


def get_io() -> FileIO:
    if WIN:
        from superfastfiles.engine.copier_win import WinIO
        return WinIO()
    from superfastfiles.engine.copier_posix import PosixIO
    return PosixIO()


def _key(name: str) -> str:
    return name.lower() if WIN else name


class JobError(Exception):
    """Problema que impede a tarefa de começar (mensagem para o usuário)."""


class Runner:
    def __init__(self, spec: JobSpec, io: FileIO | None = None):
        self.spec = spec
        self.io = io or get_io()
        self.stats = JobStats()
        self.plan: list[PlanItem] = []
        self._cancel = threading.Event()
        self._running = threading.Event()
        self._running.set()
        self._lock = threading.Lock()
        self.filters = Filters(spec.include, spec.exclude, spec.min_size, spec.max_size,
                               spec.newer_than, spec.older_than)

    # Controle (de outra thread) ----------------------------------------------------
    def pause(self): self._running.clear()
    def resume(self): self._running.set()

    def cancel(self):
        self._cancel.set()
        self._running.set()

    @property
    def paused(self) -> bool: return not self._running.is_set()
    @property
    def cancelled(self) -> bool: return self._cancel.is_set()

    # ---------------------------------------------------------------------------------
    def run(self) -> JobStats:
        try:
            if self.spec.mode == Mode.DELETE:
                self._delete_job()
            else:
                self._copy_job()
        finally:
            import time
            self.stats.scanning = False
            self.stats.current = ""
            self.stats.finished = time.monotonic()
        return self.stats

    def _roots(self) -> list[tuple[str, str]]:
        """(origem com caminho longo, nome dela no destino). Origem terminada em barra = só o conteúdo."""
        roots = []
        for s in self.spec.sources:
            s = s.strip()
            if not s:
                continue
            contents = s.endswith(("/", "\\")) and len(s) > 1
            p = long_path(s)
            name = os.path.basename(os.path.abspath(s).rstrip("/\\"))
            rel = "" if contents or not name or (WIN and name.endswith(":")) else name
            roots.append((p.rstrip("/\\") if rel else p, rel))
        if not roots:
            raise JobError(tr("Escolha pelo menos uma origem."))
        return roots

    # Copiar / Mover / Sincronizar --------------------------------------------------
    def _copy_job(self):
        spec, stats = self.spec, self.stats
        if not spec.dest.strip():
            raise JobError(tr("Escolha a pasta de destino."))
        roots = self._roots()
        dest = long_path(spec.dest)
        for src, _rel in roots:
            a, b = os.path.normcase(src), os.path.normcase(dest)
            if os.path.isdir(src) and (a == b or b.startswith(a.rstrip("\\/") + os.sep)):
                raise JobError(tr("O destino fica dentro da origem ({path}): a cópia não teria fim.",
                                  path=display_path(src)))
        if not spec.dry_run:
            os.makedirs(dest, exist_ok=True)

        strat = choose_strategy(disk_info(roots[0][0]), disk_info(dest), spec.disk_mode, spec.threads,
                                spec.buffer_mb)
        stats.strategy = f"{strat.name} · {self.io.name}"
        stats.note(tr("Estratégia: {name} · {threads} threads, blocos de {mb} MB", name=stats.strategy,
                      threads=strat.small_threads, mb=strat.chunk >> 20))

        if spec.mode == Mode.MOVE and not spec.dry_run and not self.filters.active:
            roots = self._move_by_rename(roots, dest)
            if not roots:
                return

        self.copier = Copier(self.io, strat.chunk, strat.depth)
        self.native_large = True if strat.mode == "net" else None    # rede: cópia no servidor pelo SO
        self.dest = dest
        self.dir_cache: dict[str, object] = {dest: _LAZY}
        self.dir_times: list[tuple[str, Entry]] = []
        self.listings: dict[str, set] = {}
        self.moved_ok: list[str] = []
        self.src_dirs: list[str] = []

        q: queue.Queue = queue.Queue(maxsize=50_000)
        scanner = Scanner(roots, self.filters, q, stats.error, strat.scan_threads,
                          want_listings=spec.mode == Mode.SYNC, cancel=self._cancel)
        small = ThreadPoolExecutor(strat.small_threads, thread_name_prefix="small")
        large = ThreadPoolExecutor(strat.large_threads, thread_name_prefix="large")
        slots = threading.BoundedSemaphore(strat.small_threads * 4 + strat.large_threads * 2)
        scanner.start()
        try:
            while True:
                item = q.get()
                if item is DONE or self._cancel.is_set():
                    break
                if isinstance(item, DirListing):
                    self.listings[item.rel] = item.names
                elif item.kind == "dir":
                    self._on_dir(item)
                elif item.kind == "file":
                    self._on_file(item, small, large, slots)
                else:
                    self._on_link(item)
            stats.scanning = False
        finally:
            small.shutdown(wait=True, cancel_futures=self._cancel.is_set())
            large.shutdown(wait=True, cancel_futures=self._cancel.is_set())
        if self._cancel.is_set():
            stats.note(tr("Cancelado pelo usuário"))
            return
        if spec.mode == Mode.SYNC:
            self._sync_delete()
        if (spec.preserve_times or spec.extras) and not spec.dry_run:
            for path, e in sorted(self.dir_times, key=lambda x: -x[0].count(os.sep)):
                if spec.extras:
                    self._extras(e.src, path, True)
                if spec.preserve_times:
                    try:
                        metadata.set_times(path, e.atime_ns, e.mtime_ns)
                    except OSError:
                        pass
        if spec.mode == Mode.MOVE and not spec.dry_run:
            self._delete_moved_sources(roots)

    def _move_by_rename(self, roots, dest):
        """Mover no mesmo volume: renomear é instantâneo (não copia nada). Sobra o que não deu para renomear."""
        rest = []
        for src, rel in roots:
            target = os.path.join(dest, rel) if rel else None
            if target and not os.path.lexists(target) and metadata.same_volume(src, dest):
                try:
                    os.rename(src, target)
                    self.stats.add(done_files=1)
                    self.stats.note(tr("Movido (renomeado) {src} -> {dst}", src=display_path(src),
                                       dst=display_path(target)))
                    continue
                except OSError:
                    pass
            rest.append((src, rel))
        return rest

    def _listing(self, folder: str):
        v = self.dir_cache.get(folder, _LAZY)
        if v is _LAZY:
            v = metadata.list_dir(folder)
            self.dir_cache[folder] = v
        return v

    def _on_dir(self, e: Entry):
        dst = os.path.join(self.dest, e.rel)
        parent = self._listing(os.path.dirname(dst))
        info = parent.get(_key(os.path.basename(dst))) if parent else None
        if self.spec.mode == Mode.MOVE:
            self.src_dirs.append(e.src)
        if info is not None and not info[2]:
            self.stats.error(display_path(e.src), tr("no destino existe um arquivo com o nome desta pasta"))
            self.dir_cache[dst] = {}
            return
        if info is None:
            self.dir_cache[dst] = None          # vai ser criada agora: nada dentro
            if self.spec.dry_run:
                self.plan.append(PlanItem("mkdir", display_path(dst)))
            else:
                try:
                    os.makedirs(dst, exist_ok=True)
                    self.stats.add(dirs_created=1)
                except OSError as ex:
                    self.stats.error(display_path(dst), ex.strerror or str(ex))
                    return
        else:
            self.dir_cache[dst] = _LAZY          # já existe: lê o conteúdo só se algum arquivo precisar
        self.dir_times.append((dst, e))

    def _decide(self, e: Entry, info) -> str | None:
        """'copy' | 'overwrite' | 'error' | None (pular)."""
        if info is None:
            return "copy"
        size, mtime, is_dir = info
        if is_dir:
            return "error"
        ow = self.spec.overwrite
        if ow == Overwrite.ALWAYS:
            return "overwrite"
        if ow == Overwrite.NEVER:
            return None
        if ow == Overwrite.NEWER:
            return "overwrite" if e.mtime_ns > mtime + TIME_TOLERANCE_NS else None
        same = size == e.size and abs(mtime - e.mtime_ns) <= TIME_TOLERANCE_NS
        return None if same else "overwrite"

    def _on_file(self, e: Entry, small, large, slots):
        dst = os.path.join(self.dest, e.rel)
        parent = self._listing(os.path.dirname(dst))
        info = parent.get(_key(os.path.basename(dst))) if parent else None
        action = self._decide(e, info)
        if action == "error":
            self.stats.error(display_path(e.src), tr("no destino existe uma pasta com o nome deste arquivo"))
            return
        if action is None:
            self.stats.add(skipped_files=1, skipped_bytes=e.size)
            if self.spec.mode == Mode.MOVE and info is not None and info[0] == e.size:
                self.moved_ok.append(e.src)
            if self.spec.dry_run:
                self.plan.append(PlanItem("skip", display_path(e.src), e.size))
            return
        self.stats.add(scan_files=1, scan_bytes=e.size)
        if self.spec.dry_run:
            self.plan.append(PlanItem(action, display_path(e.src), e.size))
            self.stats.add(done_files=1, done_bytes=e.size)
            return
        while not slots.acquire(timeout=0.2):
            if self._cancel.is_set():
                return
        pool = large if e.size > LARGE else small
        fut = pool.submit(self._copy_one, e, dst, info is not None)
        fut.add_done_callback(lambda _f: slots.release())

    def _copy_one(self, e: Entry, dst: str, existed: bool):
        if self._cancel.is_set():
            return
        stats = self.stats
        stats.current = display_path(e.src)
        sent = [0]

        def progress(n, _b=stats.bytes_done):
            sent[0] += n
            _b(n)

        spec = self.spec
        ctx = CopyContext(progress, self._cancel, self._running, spec.verify, spec.unbuffered, spec.native,
                          spec.preserve_times, native_large=self.native_large)
        try:
            try:
                self.copier.copy(e.src, dst, e.size, e.mtime_ns, e.atime_ns, e.mode, ctx)
            except PermissionError:
                if not existed:
                    raise
                metadata.make_writable(dst)          # destino "somente leitura": libera e tenta de novo
                stats.bytes_done(-sent[0])
                sent[0] = 0
                self.copier.copy(e.src, dst, e.size, e.mtime_ns, e.atime_ns, e.mode, ctx)
            if spec.extras:
                self._extras(e.src, dst, False)
            stats.add(done_files=1, verified_files=1 if spec.verify else 0)
            if spec.mode == Mode.MOVE:
                with self._lock:
                    self.moved_ok.append(e.src)
        except Cancelled:
            stats.bytes_done(-sent[0])
        except VerifyError as ex:
            stats.bytes_done(-sent[0])
            stats.error(display_path(e.src), str(ex))
        except OSError as ex:
            stats.bytes_done(-sent[0])
            stats.error(display_path(e.src), ex.strerror or str(ex))

    def _extras(self, src: str, dst: str, is_dir: bool):
        """Modo servidor: permissões e dados extras. Se falhar, o conteúdo já está copiado: só registra."""
        try:
            extras.copy_extras(src, dst, is_dir, self.spec.preserve_times)
        except OSError as ex:
            self.stats.error(display_path(src), tr("permissões e dados extras: {error}", error=ex.strerror or ex))

    def _on_link(self, e: Entry):
        dst = os.path.join(self.dest, e.rel)
        if self.spec.dry_run:
            self.plan.append(PlanItem("link", display_path(e.src)))
            return
        try:
            if WIN and os.path.isjunction(e.src):
                self.stats.note(tr("Ignorado (junção do Windows): {path}", path=display_path(e.src)))
                return
            metadata.copy_link(e.src, dst)
            self.stats.add(done_files=1)
        except OSError as ex:
            self.stats.error(display_path(e.src), tr("link simbólico: {error}", error=ex.strerror or ex))

    def _sync_delete(self):
        """Apaga no destino o que não existe mais na origem (só nas pastas que foram lidas por inteiro)."""
        f = self.filters
        for rel, names in self.listings.items():
            if self._cancel.is_set():
                return
            folder = os.path.join(self.dest, rel) if rel else self.dest
            have = metadata.list_dir(folder)
            if not have:
                continue
            try:
                real_names = {(_key(n)): n for n in os.listdir(folder)}
            except OSError:
                continue
            for k, (size, mtime, is_dir) in have.items():
                if k in names:
                    continue
                name = real_names.get(k, k)
                child_rel = os.path.join(rel, name) if rel else name
                if is_dir and not f.dir_ok(name, child_rel):
                    continue           # excluída pelo filtro: fica como está
                if not is_dir and not f.dir_ok(name, child_rel):
                    continue
                path = os.path.join(folder, name)
                if self.spec.dry_run:
                    self.plan.append(PlanItem("delete", display_path(path), size))
                    continue
                self._remove(path, is_dir)

    def _remove(self, path: str, is_dir: bool):
        try:
            if is_dir:
                n = sum(len(fs) for _r, _d, fs in os.walk(path))
                shutil.rmtree(path, onexc=_rm_readonly)
                self.stats.add(deleted_dirs=1, deleted_files=n)
            else:
                try:
                    os.remove(path)
                except PermissionError:
                    metadata.make_writable(path)
                    os.remove(path)
                self.stats.add(deleted_files=1)
            self.stats.note(tr("Apagado no destino: {path}", path=display_path(path)))
        except OSError as ex:
            self.stats.error(display_path(path), ex.strerror or str(ex))

    def _delete_moved_sources(self, roots):
        for p in self.moved_ok:
            try:
                try:
                    os.remove(p)
                except PermissionError:
                    metadata.make_writable(p)
                    os.remove(p)
            except OSError as ex:
                self.stats.error(display_path(p), tr("não foi possível apagar a origem: {error}", error=ex.strerror or ex))
        dirs = sorted(set(self.src_dirs) | {s for s, rel in roots if rel and os.path.isdir(s)},
                      key=lambda d: -d.count(os.sep))
        for d in dirs:
            try:
                os.rmdir(d)
            except OSError:
                pass            # sobrou algo (erro ou filtro): a pasta fica

    # Apagar --------------------------------------------------------------------------
    def _delete_job(self):
        stats, spec = self.stats, self.spec
        roots = [(long_path(s), s) for s in spec.sources if s.strip()]
        if not roots:
            raise JobError(tr("Escolha o que apagar."))
        stats.strategy = tr("Apagar em paralelo")
        q: queue.Queue = queue.Queue(maxsize=50_000)
        scan_roots = []
        files_top = []
        for p, orig in roots:
            if os.path.isdir(p) and not os.path.islink(p):
                scan_roots.append((p, ""))
            elif os.path.lexists(p):
                files_top.append(p)
            else:
                stats.error(orig, tr("não encontrado"))
        dirs = [p for p, orig in roots if os.path.isdir(p) and not os.path.islink(p)
                and not orig.endswith(("/", "\\"))]
        workers = ThreadPoolExecutor(16, thread_name_prefix="del")
        for p in files_top:
            self._del_file(p, 0, workers)
        if scan_roots:
            scanner = Scanner(scan_roots, self.filters, q, stats.error, 8, cancel=self._cancel)
            scanner.start()
            while True:
                item = q.get()
                if item is DONE or self._cancel.is_set():
                    break
                if isinstance(item, Entry):
                    if item.kind == "dir":
                        dirs.append(item.src)
                    else:
                        self._del_file(item.src, item.size, workers)
        stats.scanning = False
        workers.shutdown(wait=True, cancel_futures=self._cancel.is_set())
        if self._cancel.is_set():
            return
        for d in sorted(set(dirs), key=lambda d: -d.count(os.sep)):
            if spec.dry_run:
                self.plan.append(PlanItem("rmdir", display_path(d)))
                continue
            try:
                os.rmdir(d)
                stats.add(deleted_dirs=1)
            except OSError:
                pass

    def _del_file(self, path: str, size: int, workers):
        self.stats.add(scan_files=1, scan_bytes=size)
        if self.spec.dry_run:
            self.plan.append(PlanItem("delete", display_path(path), size))
            self.stats.add(done_files=1, done_bytes=size)
            return

        def work():
            if self._cancel.is_set():
                return
            if not self._running.is_set():
                self._running.wait()
            try:
                try:
                    os.remove(path)
                except PermissionError:
                    metadata.make_writable(path)
                    os.remove(path)
                self.stats.add(done_files=1, deleted_files=1, done_bytes=size)
            except OSError as ex:
                self.stats.error(display_path(path), ex.strerror or str(ex))
        workers.submit(work)


def _rm_readonly(func, path, _exc):
    os.chmod(path, st.S_IWRITE)
    func(path)
