"""Caminhos longos, datas, permissões e leitura do destino."""
from __future__ import annotations

import os
import stat as st
import sys

WIN = sys.platform == "win32"


def long_path(p: str) -> str:
    r"""Windows: prefixo \\?\ para passar de 260 caracteres (e aceitar nomes com espaço/ponto no fim)."""
    if not WIN:
        return os.path.abspath(p)
    p = os.path.abspath(p)
    if p.startswith("\\\\?\\"):
        return p
    if p.startswith("\\\\"):                     # \\servidor\pasta -> \\?\UNC\servidor\pasta
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p


def display_path(p: str) -> str:
    """Caminho sem o prefixo \\?\\ (para mostrar ao usuário)."""
    if p.startswith("\\\\?\\UNC\\"):
        return "\\\\" + p[8:]
    if p.startswith("\\\\?\\"):
        return p[4:]
    return p


def same_volume(a: str, b: str) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def set_times(path: str, atime_ns: int, mtime_ns: int) -> None:
    os.utime(path, ns=(atime_ns or mtime_ns, mtime_ns), follow_symlinks=False) if not WIN else \
        os.utime(path, ns=(atime_ns or mtime_ns, mtime_ns))


def copy_mode(path: str, mode: int) -> None:
    if WIN:
        # No Windows só existe "somente leitura"; o resto dos atributos o CopyFile já leva.
        if not mode & st.S_IWRITE:
            try:
                os.chmod(path, st.S_IREAD)
            except OSError:
                pass
        return
    try:
        os.chmod(path, st.S_IMODE(mode))
    except OSError:
        pass


def make_writable(path: str) -> None:
    """Tira o "somente leitura" para conseguir sobrescrever ou apagar."""
    try:
        os.chmod(path, st.S_IWRITE | st.S_IREAD)
    except OSError:
        pass


def list_dir(path: str) -> dict[str, tuple[int, int, bool]] | None:
    """{nome (minúsculo no Windows): (tamanho, mtime_ns, é_pasta)} ou None se a pasta não existir."""
    try:
        it = os.scandir(path)
    except FileNotFoundError:
        return None
    except NotADirectoryError:
        return None
    out = {}
    with it:
        for de in it:
            try:
                s = de.stat(follow_symlinks=False)
            except OSError:
                continue
            out[de.name.lower() if WIN else de.name] = (s.st_size, s.st_mtime_ns, st.S_ISDIR(s.st_mode))
    return out


def copy_link(src: str, dst: str) -> None:
    """Recria um link simbólico (o alvo não é copiado)."""
    target = os.readlink(src)
    if os.path.lexists(dst):
        os.unlink(dst)
    os.symlink(target, dst, target_is_directory=os.path.isdir(src))
