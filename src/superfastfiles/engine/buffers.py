"""Buffers alinhados reaproveitados.

`mmap` anônimo devolve memória alinhada à página (4 KB ou 64 KB no Windows) em todos os sistemas — exigência da
E/S sem cache (FILE_FLAG_NO_BUFFERING / O_DIRECT). Alocar uma vez e reaproveitar evita custo de alocação e
falhas de página a cada arquivo.
"""
from __future__ import annotations

import ctypes
import mmap
import queue

ALIGN = 4096        # múltiplo de qualquer setor (512 e 4Kn)


def align_up(n: int, a: int = ALIGN) -> int:
    return (n + a - 1) // a * a


class Buffer:
    __slots__ = ("mm", "size", "addr", "view", "n")

    def __init__(self, size: int):
        self.size = align_up(size)
        self.mm = mmap.mmap(-1, self.size)
        self.addr = ctypes.addressof(ctypes.c_char.from_buffer(self.mm))
        self.view = memoryview(self.mm)
        self.n = 0                  # bytes válidos


class BufferPool:
    def __init__(self, count: int, size: int):
        self.size = align_up(size)
        self._q: queue.Queue[Buffer] = queue.Queue()
        for _ in range(count):
            self._q.put(Buffer(self.size))

    def get(self, timeout: float | None = None) -> Buffer:
        return self._q.get(timeout=timeout)

    def put(self, b: Buffer) -> None:
        b.n = 0
        self._q.put(b)
