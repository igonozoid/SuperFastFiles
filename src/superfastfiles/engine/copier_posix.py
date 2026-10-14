"""Linux e macOS.

Linux, nativo (sem verificação), em ordem:
  1. FICLONE (reflink): Btrfs, XFS, bcachefs... a cópia é instantânea (compartilha os blocos).
  2. os.copy_file_range: cópia dentro do kernel, sem passar pelo Python; em NFS 4.2/SMB3 vira cópia no
     servidor. Feita em fatias de 64 MB para mostrar o progresso e permitir pausar/cancelar.
  Pipeline: posix_fadvise(SEQUENTIAL) na leitura e DONTNEED depois (não suja o cache com arquivos enormes).

macOS, nativo: clonefile (APFS, instantâneo) e fcopyfile (cópia do kernel, arquivos pequenos).
  Pipeline: F_NOCACHE (equivalente ao sem cache do Windows).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import errno
import fcntl
import os
import sys

from superfastfiles.engine.buffers import Buffer
from superfastfiles.engine.copier_base import CopyContext, FileIO, ReadHandle, WriteHandle, _PosixRead, _PosixWrite

LINUX = sys.platform.startswith("linux")
MAC = sys.platform == "darwin"
FICLONE = 0x40049409
F_NOCACHE = 48
SLICE = 64 << 20


class PosixRead(_PosixRead):
    def __init__(self, path: str, unbuffered: bool):
        super().__init__(path)
        self.unbuffered = unbuffered
        if LINUX:
            try:
                os.posix_fadvise(self.fd, 0, 0, os.POSIX_FADV_SEQUENTIAL)
            except OSError:
                pass
        elif MAC and unbuffered:
            try:
                fcntl.fcntl(self.fd, F_NOCACHE, 1)
            except OSError:
                pass

    def close(self):
        if LINUX and self.unbuffered:
            try:
                os.posix_fadvise(self.fd, 0, 0, os.POSIX_FADV_DONTNEED)
            except OSError:
                pass
        super().close()


class PosixWrite(_PosixWrite):
    def __init__(self, path: str, unbuffered: bool):
        super().__init__(path)
        if MAC and unbuffered:
            try:
                fcntl.fcntl(self.fd, F_NOCACHE, 1)
            except OSError:
                pass


class PosixIO(FileIO):
    name = "Linux (kernel)" if LINUX else "macOS (kernel)" if MAC else "POSIX"

    def __init__(self):
        self._reflink_ok = True
        self._cfr_ok = hasattr(os, "copy_file_range")
        self._clonefile = None
        if MAC:
            try:
                libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
                libc.clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
                libc.clonefile.restype = ctypes.c_int
                self._clonefile = libc.clonefile
            except (OSError, AttributeError):
                self._clonefile = None

    def open_read(self, path, unbuffered) -> ReadHandle:
        return PosixRead(path, unbuffered)

    def open_write(self, path, size, unbuffered) -> WriteHandle:
        return PosixWrite(path, unbuffered)

    def native_copy(self, src, dst, size, ctx: CopyContext, large: bool) -> bool:
        if MAC:
            return self._mac(src, dst, size, ctx, large)
        if LINUX:
            return self._linux(src, dst, size, ctx)
        return False

    # Linux -------------------------------------------------------------------
    def _linux(self, src, dst, size, ctx) -> bool:
        fin = os.open(src, os.O_RDONLY)
        try:
            fout = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)
        except BaseException:
            os.close(fin)
            raise
        ok = False
        try:
            if self._reflink_ok and size:
                try:
                    fcntl.ioctl(fout, FICLONE, fin)
                    ctx.progress(size)
                    ok = True
                    return True
                except OSError as e:
                    if e.errno in (errno.ENOTTY, errno.EINVAL, errno.EOPNOTSUPP, errno.ENOSYS):
                        pass        # sistema de arquivos sem reflink: segue
                    elif e.errno != errno.EXDEV:
                        raise
            if not self._cfr_ok:
                return False
            done = 0
            while True:
                ctx.checkpoint()
                try:
                    n = os.copy_file_range(fin, fout, SLICE)
                except OSError as e:
                    if done == 0 and e.errno in (errno.EXDEV, errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
                        return False        # kernel antigo ou par de sistemas não suportado: usa o pipeline
                    raise
                if n == 0:
                    break
                done += n
                ctx.progress(n)
            ok = True
            return True
        finally:
            os.close(fin)
            os.close(fout)
            if not ok:
                try:
                    os.unlink(dst)
                except OSError:
                    pass

    # macOS -------------------------------------------------------------------
    def _mac(self, src, dst, size, ctx, large) -> bool:
        if self._clonefile is not None:
            if os.path.lexists(dst):
                os.unlink(dst)
            if self._clonefile(os.fsencode(src), os.fsencode(dst), 0) == 0:
                ctx.progress(size)
                return True
        if large:
            return False            # fcopyfile não mostra progresso: arquivos grandes vão pelo pipeline
        import posix
        fcopy = getattr(posix, "_fcopyfile", None)
        if fcopy is None:
            return False
        with open(src, "rb") as fi, open(dst, "wb") as fo:
            fcopy(fi.fileno(), fo.fileno(), posix._COPYFILE_DATA)
        ctx.progress(size)
        return True
