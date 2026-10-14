"""Cópia de um arquivo: caminho nativo do SO ou pipeline próprio (leitora + escritora).

Pipeline (arquivos grandes): uma thread lê o próximo bloco enquanto a outra grava o anterior, com buffers
alinhados reaproveitados. Leitura e escrita acontecem ao mesmo tempo — em discos diferentes isso chega perto da
velocidade do disco mais lento. As chamadas de E/S soltam o GIL, então as threads correm em paralelo de verdade.

Cada sistema implementa `FileIO` (abrir/ler/gravar com ou sem cache) e, se tiver, `native_copy` (CopyFileEx,
copy_file_range, clonefile...). Sem verificação, o nativo costuma ser o mais rápido; com verificação, o pipeline
calcula o hash do que leu da origem (sem ler duas vezes) e depois relê o destino sem cache.
"""
from __future__ import annotations

import os
import queue
import threading
from dataclasses import dataclass, field
from typing import Callable

from superfastfiles.engine.buffers import Buffer, BufferPool
from superfastfiles.engine.verify import VerifyError, new_hasher


class Cancelled(Exception):
    pass


@dataclass
class CopyContext:
    progress: Callable[[int], None]
    cancel: threading.Event
    running: threading.Event               # limpo = pausado
    verify: bool = False
    unbuffered: bool = True
    native: bool = True
    preserve_times: bool = True
    unbuffered_min: int = 32 << 20         # arquivos menores que isso usam cache do SO (mais rápido para eles)
    native_large: bool | None = None       # None = o padrão do sistema (FileIO.native_large)
    extra: dict = field(default_factory=dict)

    def checkpoint(self):
        if not self.running.is_set():
            self.running.wait()
        if self.cancel.is_set():
            raise Cancelled()


class ReadHandle:
    def readinto(self, buf: Buffer, n: int) -> int: raise NotImplementedError
    def close(self): pass


class WriteHandle:
    def write(self, buf: Buffer, n: int) -> None: raise NotImplementedError
    def finish(self, size: int, src: ReadHandle | None, src_path: str, mtime_ns: int, atime_ns: int,
               mode: int, preserve_times: bool) -> None: raise NotImplementedError
    def close(self): pass
    def abort(self): pass


class FileIO:
    """Camada de E/S por sistema. A genérica usa os.open/os.readv/os.write."""
    name = "genérico"
    native_large = True        # False: arquivos grandes sempre pelo pipeline (medido mais rápido no Windows)

    def open_read(self, path: str, unbuffered: bool) -> ReadHandle:
        return _PosixRead(path)

    def open_write(self, path: str, size: int, unbuffered: bool) -> WriteHandle:
        return _PosixWrite(path)

    def native_copy(self, src: str, dst: str, size: int, ctx: CopyContext, large: bool) -> bool:
        """Cópia pelo próprio SO. Retorna False se não houver/não der (aí usa o pipeline)."""
        return False

    def after_native(self, dst: str, mtime_ns: int, atime_ns: int, mode: int, preserve_times: bool) -> None:
        from superfastfiles.engine import metadata
        if preserve_times:
            metadata.set_times(dst, atime_ns, mtime_ns)
        metadata.copy_mode(dst, mode)


class _PosixRead(ReadHandle):
    def __init__(self, path: str):
        self.fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))

    def readinto(self, buf: Buffer, n: int) -> int:
        view = buf.view[:n]
        got = 0
        while got < n:
            r = os.readv(self.fd, [view[got:]])
            if r == 0:
                break
            got += r
        return got

    def close(self):
        os.close(self.fd)


class _PosixWrite(WriteHandle):
    def __init__(self, path: str):
        self.path = path
        self.fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o666)
        self.closed = False

    def write(self, buf: Buffer, n: int) -> None:
        view = buf.view[:n]
        done = 0
        while done < n:
            done += os.write(self.fd, view[done:])

    def finish(self, size, src, src_path, mtime_ns, atime_ns, mode, preserve_times):
        self.close()
        from superfastfiles.engine import metadata
        if preserve_times:
            metadata.set_times(self.path, atime_ns, mtime_ns)
        metadata.copy_mode(self.path, mode)

    def close(self):
        if not self.closed:
            self.closed = True
            os.close(self.fd)

    def abort(self):
        self.close()
        try:
            os.unlink(self.path)
        except OSError:
            pass


class Copier:
    """Copia um arquivo usando a FileIO do sistema. Uma instância serve todas as threads."""

    def __init__(self, io: FileIO, chunk: int, depth: int):
        self.io = io
        self.chunk = chunk          # tamanho do bloco do pipeline
        self.depth = depth          # blocos em voo por arquivo grande
        self._local = threading.local()

    # Buffers por thread: as threads de arquivos pequenos usam 1, as de grandes usam `depth`.
    def _pool(self, large: bool) -> BufferPool:
        key = "large" if large else "small"
        pool = getattr(self._local, key, None)
        if pool is None:
            pool = BufferPool(self.depth, self.chunk) if large else BufferPool(1, min(self.chunk, 1 << 20))
            setattr(self._local, key, pool)
        return pool

    def copy(self, src: str, dst: str, size: int, mtime_ns: int, atime_ns: int, mode: int, ctx: CopyContext) -> None:
        ctx.checkpoint()
        large = size > (1 << 20)
        native_large = self.io.native_large if ctx.native_large is None else ctx.native_large
        use_native = not ctx.verify and ctx.native and (not large or native_large)
        if use_native and self.io.native_copy(src, dst, size, ctx, large):
            self.io.after_native(dst, mtime_ns, atime_ns, mode, ctx.preserve_times)
            return
        unbuffered = ctx.unbuffered and size >= ctx.unbuffered_min
        digest = (self._pipeline if large else self._simple)(src, dst, size, mtime_ns, atime_ns, mode, ctx,
                                                             unbuffered)
        if ctx.verify:
            self.verify(dst, size, digest, ctx)

    # Arquivo pequeno: um buffer, sem thread extra
    def _simple(self, src, dst, size, mtime_ns, atime_ns, mode, ctx, unbuffered):
        pool = self._pool(False)
        buf = pool.get()
        hasher = new_hasher() if ctx.verify else None
        rh = self.io.open_read(src, unbuffered)
        try:
            wh = self.io.open_write(dst, size, unbuffered)
            try:
                while True:
                    n = rh.readinto(buf, pool.size)
                    if n == 0:
                        break
                    if hasher:
                        hasher.update(buf.view[:n])
                    wh.write(buf, n)
                    ctx.progress(n)
                    if n < pool.size:
                        break
                wh.finish(size, rh, src, mtime_ns, atime_ns, mode, ctx.preserve_times)
            except BaseException:
                wh.abort()
                raise
            finally:
                wh.close()
        finally:
            rh.close()
            pool.put(buf)
        return hasher.digest() if hasher else None

    # Arquivo grande: leitora em outra thread, escritora nesta
    def _pipeline(self, src, dst, size, mtime_ns, atime_ns, mode, ctx, unbuffered):
        pool = self._pool(True)
        hasher = new_hasher() if ctx.verify else None
        rh = self.io.open_read(src, unbuffered)
        try:
            wh = self.io.open_write(dst, size, unbuffered)
        except BaseException:
            rh.close()
            raise
        q: queue.Queue = queue.Queue()
        stop = threading.Event()
        err: list[BaseException] = []

        def reader():
            try:
                while not stop.is_set():
                    b = pool.get()
                    b.n = rh.readinto(b, pool.size)
                    if b.n == 0:
                        pool.put(b)
                        break
                    q.put(b)
                    if b.n < pool.size:
                        break
            except BaseException as e:      # noqa: BLE001 — repassado para a thread que grava
                err.append(e)
            finally:
                q.put(None)

        t = threading.Thread(target=reader, name="reader", daemon=True)
        t.start()
        ended = False
        try:
            while True:
                b = q.get()
                if b is None:
                    ended = True
                    break
                try:
                    ctx.checkpoint()
                    if hasher:
                        hasher.update(b.view[:b.n])
                    wh.write(b, b.n)
                    ctx.progress(b.n)
                finally:
                    pool.put(b)
            t.join()
            if err:
                raise err[0]
            wh.finish(size, rh, src, mtime_ns, atime_ns, mode, ctx.preserve_times)
        except BaseException:
            stop.set()
            while not ended:                     # devolve os buffers e deixa a leitora terminar
                b = q.get()
                if b is None:
                    break
                pool.put(b)
            t.join()
            wh.abort()
            raise
        finally:
            wh.close()
            rh.close()
        return hasher.digest() if hasher else None

    def verify(self, dst: str, size: int, expected: bytes | None, ctx: CopyContext) -> None:
        """Relê o destino sem cache do SO (lê do disco de verdade) e compara o hash."""
        pool = self._pool(size > (1 << 20))
        buf = pool.get()
        hasher = new_hasher()
        total = 0
        rh = self.io.open_read(dst, True)
        try:
            while True:
                ctx.checkpoint()
                n = rh.readinto(buf, pool.size)
                if n == 0:
                    break
                hasher.update(buf.view[:n])
                total += n
                if n < pool.size:
                    break
        finally:
            rh.close()
            pool.put(buf)
        if total != size or hasher.digest() != expected:
            raise VerifyError("o conteúdo gravado no destino não confere com a origem")
