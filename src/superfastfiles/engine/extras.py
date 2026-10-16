"""Opção "modo servidor": permissões e dados extras dos arquivos. Desligada por padrão.

Para backup pessoal não faz diferença; em servidor de arquivos importa quem pode abrir cada pasta.

- Windows: permissões (ACL: DACL e, se o programa rodar como administrador, também dono e grupo) e fluxos
  alternativos (ADS — dados extras gravados "dentro" do arquivo, como a marca "baixado da internet").
- Linux: atributos estendidos (xattr, que incluem as ACLs POSIX) e, como root, dono e grupo.
- macOS: ACL e atributos estendidos (copyfile do sistema) e, como root, dono e grupo.

Cada função levanta OSError; quem chama registra o erro e segue (a cópia do conteúdo já está feita).
"""
from __future__ import annotations

import os
import sys

WIN = sys.platform == "win32"
LINUX = sys.platform.startswith("linux")
MAC = sys.platform == "darwin"


def copy_extras(src: str, dst: str, is_dir: bool = False, preserve_times: bool = True) -> None:
    if WIN:
        # Ordem: fluxos -> datas -> ACL. Gravar um fluxo muda a data do arquivo (então a data volta depois),
        # e a ACL copiada pode tirar do próprio usuário a permissão de gravar (então ela vai por último).
        if _win_streams(src, dst, is_dir) and preserve_times:
            s = os.stat(src)
            os.utime(dst, ns=(s.st_atime_ns, s.st_mtime_ns))
        _win_security(src, dst)
    elif LINUX:
        _linux(src, dst)
    elif MAC:
        _mac(src, dst)


# Windows ----------------------------------------------------------------------------------
if WIN:
    import ctypes
    from ctypes import wintypes as wt

    _adv = ctypes.WinDLL("advapi32", use_last_error=True)
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _adv.GetFileSecurityW.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
    _adv.GetFileSecurityW.restype = wt.BOOL
    _adv.SetFileSecurityW.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.c_void_p]
    _adv.SetFileSecurityW.restype = wt.BOOL

    OWNER, GROUP, DACL = 0x1, 0x2, 0x4
    PROTECTED_DACL, UNPROTECTED_DACL = 0x80000000, 0x20000000
    _SE_DACL_PROTECTED = 0x1000

    class _WIN32_FIND_STREAM_DATA(ctypes.Structure):
        _fields_ = [("StreamSize", ctypes.c_int64), ("cStreamName", ctypes.c_wchar * 296)]

    _k32.FindFirstStreamW.argtypes = [wt.LPCWSTR, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
    _k32.FindFirstStreamW.restype = wt.HANDLE
    _k32.FindNextStreamW.argtypes = [wt.HANDLE, ctypes.c_void_p]
    _k32.FindNextStreamW.restype = wt.BOOL
    _k32.FindClose.argtypes = [wt.HANDLE]
    _INVALID = wt.HANDLE(-1).value
    ERROR_HANDLE_EOF = 38

    _privileges_done = False

    def _enable_privileges():
        """Como administrador, liga os privilégios de backup/restauração (permitem gravar o dono original)."""
        global _privileges_done
        if _privileges_done:
            return
        _privileges_done = True
        try:
            class LUID(ctypes.Structure):
                _fields_ = [("Low", wt.DWORD), ("High", wt.LONG)]

            class TP(ctypes.Structure):
                _fields_ = [("Count", wt.DWORD), ("Luid", LUID), ("Attributes", wt.DWORD)]

            token = wt.HANDLE()
            if not _adv.OpenProcessToken(_k32.GetCurrentProcess(), 0x20 | 0x8, ctypes.byref(token)):
                return
            for name in ("SeRestorePrivilege", "SeBackupPrivilege", "SeSecurityPrivilege"):
                luid = LUID()
                if _adv.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
                    tp = TP(1, luid, 0x2)
                    _adv.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
            _k32.CloseHandle(token)
        except (OSError, AttributeError):
            pass

    def _get_sd(path: str, info: int) -> ctypes.Array | None:
        need = wt.DWORD(0)
        _adv.GetFileSecurityW(path, info, None, 0, ctypes.byref(need))
        if not need.value:
            return None
        buf = ctypes.create_string_buffer(need.value)
        if not _adv.GetFileSecurityW(path, info, buf, need.value, ctypes.byref(need)):
            return None
        return buf

    def _win_security(src: str, dst: str) -> None:
        _enable_privileges()
        for info in (OWNER | GROUP | DACL, DACL):          # dono/grupo só dá como administrador
            sd = _get_sd(src, info)
            if sd is None:
                continue
            control = int.from_bytes(sd.raw[2:4], "little")   # SECURITY_DESCRIPTOR.Control
            flag = PROTECTED_DACL if control & _SE_DACL_PROTECTED else UNPROTECTED_DACL
            if _adv.SetFileSecurityW(dst, info | flag, sd):
                return
        e = ctypes.WinError(ctypes.get_last_error())
        e.filename = dst
        raise e

    def _streams(path: str) -> list[str]:
        data = _WIN32_FIND_STREAM_DATA()
        h = _k32.FindFirstStreamW(path, 0, ctypes.byref(data), 0)
        if h in (_INVALID, None):
            return []
        names = []
        try:
            while True:
                name = data.cStreamName                     # ":nome:$DATA"
                if name and name != "::$DATA":
                    names.append(name)
                if not _k32.FindNextStreamW(h, ctypes.byref(data)):
                    break
        finally:
            _k32.FindClose(h)
        return names

    def _win_streams(src: str, dst: str, is_dir: bool) -> bool:
        """Copia os fluxos alternativos. True se havia algum."""
        names = _streams(src)
        if not names:
            return False
        import stat as st
        readonly = not is_dir and not os.stat(dst).st_mode & st.S_IWRITE
        if readonly:
            os.chmod(dst, st.S_IWRITE | st.S_IREAD)
        try:
            for name in names:
                with open(src + name, "rb") as fi, open(dst + name, "wb") as fo:
                    while chunk := fi.read(1 << 20):
                        fo.write(chunk)
        finally:
            if readonly:
                os.chmod(dst, st.S_IREAD)
        return True


# Linux ------------------------------------------------------------------------------------
def _chown_like(src: str, dst: str) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        s = os.stat(src, follow_symlinks=False)
        os.chown(dst, s.st_uid, s.st_gid, follow_symlinks=False)


def _linux(src: str, dst: str) -> None:
    _chown_like(src, dst)
    for name in os.listxattr(src, follow_symlinks=False):
        try:
            os.setxattr(dst, name, os.getxattr(src, name, follow_symlinks=False), follow_symlinks=False)
        except PermissionError:
            if not name.startswith(("security.", "trusted.")):   # esses só como root
                raise


# macOS ------------------------------------------------------------------------------------
def _mac(src: str, dst: str) -> None:
    import ctypes
    import ctypes.util
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    COPYFILE_ACL, COPYFILE_XATTR = 1 << 0, 1 << 2
    if libc.copyfile(os.fsencode(src), os.fsencode(dst), None, COPYFILE_ACL | COPYFILE_XATTR) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), dst)
    _chown_like(src, dst)
