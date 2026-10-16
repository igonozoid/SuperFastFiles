"""Modo servidor (extras=True): permissões e dados extras. Desligado, nada disso é copiado de propósito."""
import os
import subprocess
import sys

import pytest

from superfastfiles.engine import JobSpec, Mode, Runner

WIN = sys.platform == "win32"


def _copy(src, dst, extras, **kw):
    r = Runner(JobSpec(mode=Mode.COPY, sources=[str(src) + os.sep], dest=str(dst), extras=extras, **kw))
    r.run()
    assert r.stats.errors == [], r.stats.errors
    return r


def _acl(path) -> str:
    return subprocess.run(["icacls", str(path)], capture_output=True, text=True, errors="replace").stdout


@pytest.mark.skipif(not WIN, reason="ACL e fluxos alternativos são do Windows")
@pytest.mark.parametrize("big", [False, True], ids=["pequeno", "grande-pipeline"])
@pytest.mark.parametrize("verify", [False, True], ids=["sem-verif", "verif"])
def test_windows_acl_e_fluxos(tmp_path, big, verify):
    src = tmp_path / "src"
    src.mkdir()
    f = src / "dados.bin"
    f.write_bytes(os.urandom((9 << 20) if big else 100))
    with open(str(f) + ":segredo", "wb") as s:          # fluxo alternativo (ADS)
        s.write(b"conteudo escondido")
    old = 1_600_000_000
    os.utime(f, (old, old))
    # ACL própria: tira a herança e dá acesso explícito só a quem roda o teste e a "Todos" (leitura)
    user = os.environ.get("USERNAME", "")
    subprocess.run(["icacls", str(f), "/inheritance:r", "/grant:r", f"{user}:F", "/grant:r", "*S-1-1-0:R"],
                   capture_output=True, check=True)

    _copy(src, tmp_path / "com", True, verify=verify, native=not big)
    _copy(src, tmp_path / "sem", False, verify=verify, native=not big)
    com, sem = tmp_path / "com" / "dados.bin", tmp_path / "sem" / "dados.bin"

    with open(str(com) + ":segredo", "rb") as s:
        assert s.read() == b"conteudo escondido"
    assert abs(com.stat().st_mtime - old) < 2            # gravar o fluxo não estragou a data
    assert "S-1-1-0" in _acl(com) or "Todos" in _acl(com) or "Everyone" in _acl(com)
    # sem o modo servidor a ACL fica a herdada da pasta de destino (sem a entrada explícita de "Todos")
    assert not ("Todos:(R)" in _acl(sem) or "Everyone:(R)" in _acl(sem))
    if big or verify:                                    # o pipeline não leva fluxos sem o modo servidor
        assert not os.path.exists(str(sem) + ":segredo")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="xattr do Linux")
def test_linux_xattr(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    f = src / "a.txt"
    f.write_bytes(b"x")
    try:
        os.setxattr(f, "user.teste", b"valor")
    except OSError:
        pytest.skip("sistema de arquivos sem xattr")
    _copy(src, tmp_path / "com", True, native=False)
    assert os.getxattr(tmp_path / "com" / "a.txt", "user.teste") == b"valor"
