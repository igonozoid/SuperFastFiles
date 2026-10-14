"""Windows: E/S direta na API Win32 via ctypes (sem compilar nada).

- Pipeline: CreateFileW com FILE_FLAG_NO_BUFFERING (sem cache do Windows, como o FastCopy) e
  FILE_FLAG_SEQUENTIAL_SCAN, ReadFile/WriteFile em buffers alinhados, pré-alocação do destino e ajuste do
  tamanho final (a escrita sem cache só aceita múltiplos do setor).
- Datas e atributos vão de uma vez com FILE_BASIC_INFO (uma chamada em vez de várias).
- Nativo: CopyFileExW — o Windows copia no kernel, leva datas/atributos/fluxos alternativos e usa a cópia
  no servidor (ODX/SMB) e block cloning (ReFS/Dev Drive) quando dá.

As funções ctypes soltam o GIL durante a chamada: as threads de cópia rodam em paralelo de verdade.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as wt

from superfastfiles.engine.buffers import ALIGN, Buffer, align_up
from superfastfiles.engine.copier_base import Cancelled, CopyContext, FileIO, ReadHandle, WriteHandle

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
FILE_SHARE_READ, FILE_SHARE_WRITE, FILE_SHARE_DELETE = 1, 2, 4
OPEN_EXISTING, CREATE_ALWAYS = 3, 2
FILE_FLAG_NO_BUFFERING = 0x20000000
FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_HANDLE_VALUE = wt.HANDLE(-1).value
FileBasicInfo, FileAllocationInfo, FileEndOfFileInfo = 0, 5, 6
COPY_FILE_NO_BUFFERING = 0x00001000
PROGRESS_CONTINUE, PROGRESS_CANCEL = 0, 1
ERROR_REQUEST_ABORTED = 1235
# Atributos que dá para copiar (comprimido/criptografado/esparso/reparse não se aplicam assim)
SETTABLE_ATTRS = 0x1 | 0x2 | 0x4 | 0x20 | 0x100 | 0x1000 | 0x2000


class FILE_BASIC_INFO(ctypes.Structure):
    _fields_ = [("CreationTime", ctypes.c_int64), ("LastAccessTime", ctypes.c_int64),
                ("LastWriteTime", ctypes.c_int64), ("ChangeTime", ctypes.c_int64), ("FileAttributes", wt.DWORD)]


k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE]
k32.CreateFileW.restype = wt.HANDLE
k32.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), wt.LPVOID]
k32.ReadFile.restype = wt.BOOL
k32.WriteFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), wt.LPVOID]
k32.WriteFile.restype = wt.BOOL
k32.CloseHandle.argtypes = [wt.HANDLE]
k32.CloseHandle.restype = wt.BOOL
k32.DeleteFileW.argtypes = [wt.LPCWSTR]
k32.DeleteFileW.restype = wt.BOOL
k32.SetFileInformationByHandle.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
k32.SetFileInformationByHandle.restype = wt.BOOL
k32.GetFileInformationByHandleEx.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
k32.GetFileInformationByHandleEx.restype = wt.BOOL

PROGRESS_ROUTINE = ctypes.WINFUNCTYPE(wt.DWORD, ctypes.c_int64, ctypes.c_int64, ctypes.c_int64, ctypes.c_int64,
                                      wt.DWORD, wt.DWORD, wt.HANDLE, wt.HANDLE, wt.LPVOID)
k32.CopyFileExW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, PROGRESS_ROUTINE, wt.LPVOID, ctypes.POINTER(wt.BOOL), wt.DWORD]
k32.CopyFileExW.restype = wt.BOOL


def _err(path: str) -> OSError:
    code = ctypes.get_last_error()
    e = ctypes.WinError(code)
    e.filename = path
    return e


def _open(path: str, access: int, share: int, disposition: int, flags: int):
    h = k32.CreateFileW(path, access, share, None, disposition, flags, None)
    if h == INVALID_HANDLE_VALUE or h is None:
        raise _err(path)
    return h


class WinRead(ReadHandle):
    def __init__(self, path: str, unbuffered: bool):
        self.unbuffered = unbuffered
        flags = FILE_FLAG_SEQUENTIAL_SCAN | (FILE_FLAG_NO_BUFFERING if unbuffered else 0)
        self.h = _open(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, OPEN_EXISTING,
                       flags)
        self.path = path

    def readinto(self, buf: Buffer, n: int) -> int:
        got = wt.DWORD(0)
        total = 0
        while total < n:
            if not k32.ReadFile(self.h, buf.addr + total, n - total, ctypes.byref(got), None):
                raise _err(self.path)
            if got.value == 0:
                break
            total += got.value
            if self.unbuffered and total % ALIGN:
                break              # fim do arquivo no meio de um setor
        return total

    def basic_info(self) -> FILE_BASIC_INFO | None:
        info = FILE_BASIC_INFO()
        if k32.GetFileInformationByHandleEx(self.h, FileBasicInfo, ctypes.byref(info), ctypes.sizeof(info)):
            return info
        return None

    def close(self):
        if self.h:
            k32.CloseHandle(self.h)
            self.h = None


class WinWrite(WriteHandle):
    def __init__(self, path: str, size: int, unbuffered: bool):
        self.path = path
        self.unbuffered = unbuffered
        flags = FILE_FLAG_SEQUENTIAL_SCAN | (FILE_FLAG_NO_BUFFERING if unbuffered else 0)
        self.h = _open(path, GENERIC_WRITE | GENERIC_READ, FILE_SHARE_READ, CREATE_ALWAYS, flags)
        if size > 0:                     # reserva o espaço de uma vez: menos fragmentação e menos metadados
            alloc = ctypes.c_int64(align_up(size))
            k32.SetFileInformationByHandle(self.h, FileAllocationInfo, ctypes.byref(alloc), 8)

    def write(self, buf: Buffer, n: int) -> None:
        if self.unbuffered:
            n = align_up(n)              # sem cache só grava setores inteiros; o excesso é cortado no fim
        done = wt.DWORD(0)
        off = 0
        while off < n:
            if not k32.WriteFile(self.h, buf.addr + off, n - off, ctypes.byref(done), None):
                raise _err(self.path)
            off += done.value

    def finish(self, size, src, src_path, mtime_ns, atime_ns, mode, preserve_times):
        if self.unbuffered and size % ALIGN:
            eof = ctypes.c_int64(size)
            if not k32.SetFileInformationByHandle(self.h, FileEndOfFileInfo, ctypes.byref(eof), 8):
                raise _err(self.path)
        info = src.basic_info() if isinstance(src, WinRead) else None
        if info is not None:
            if not preserve_times:
                info.CreationTime = info.LastAccessTime = info.LastWriteTime = 0
            info.ChangeTime = 0
            attrs = info.FileAttributes & SETTABLE_ATTRS
            info.FileAttributes = attrs or FILE_ATTRIBUTE_NORMAL
            k32.SetFileInformationByHandle(self.h, FileBasicInfo, ctypes.byref(info), ctypes.sizeof(info))

    def close(self):
        if self.h:
            k32.CloseHandle(self.h)
            self.h = None

    def abort(self):
        self.close()
        k32.DeleteFileW(self.path)


class WinIO(FileIO):
    name = "Windows (Win32 direto)"
    # Benchmark (tools/bench.py, SSD NVMe): nos arquivos grandes o pipeline sem cache bate o CopyFileEx;
    # nos pequenos, o CopyFileEx ganha (menos chamadas por arquivo). Em rede, o CopyFileEx faz cópia no
    # servidor (ODX/SMB), então lá ele fica também com os grandes.
    native_large = False

    def open_read(self, path, unbuffered):
        return WinRead(path, unbuffered)

    def open_write(self, path, size, unbuffered):
        return WinWrite(path, size, unbuffered)

    def native_copy(self, src, dst, size, ctx: CopyContext, large: bool) -> bool:
        cancel = wt.BOOL(False)
        last = [0]
        cb = None
        if large:
            def on_progress(total, done, *_):
                delta = done - last[0]
                last[0] = done
                if delta:
                    ctx.progress(delta)
                if not ctx.running.is_set():
                    ctx.running.wait()
                return PROGRESS_CANCEL if ctx.cancel.is_set() else PROGRESS_CONTINUE
            cb = PROGRESS_ROUTINE(on_progress)
        flags = COPY_FILE_NO_BUFFERING if (large and ctx.unbuffered and size >= ctx.unbuffered_min) else 0
        ok = k32.CopyFileExW(src, dst, cb or PROGRESS_ROUTINE(), None, ctypes.byref(cancel), flags)
        if not ok:
            code = ctypes.get_last_error()
            if code == ERROR_REQUEST_ABORTED:
                k32.DeleteFileW(dst)
                raise Cancelled()
            e = ctypes.WinError(code)
            e.filename = src
            raise e
        if not large:
            ctx.progress(size)
        elif size - last[0]:
            ctx.progress(size - last[0])
        return True

    def after_native(self, dst, mtime_ns, atime_ns, mode, preserve_times):
        # CopyFileEx já levou data de modificação e atributos; nada a fazer
        if not preserve_times:
            import os
            os.utime(dst, None)
