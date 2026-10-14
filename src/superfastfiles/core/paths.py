"""Onde ficam os dados (preferências, histórico, log). App portátil: tudo numa pasta só.

Mesma regra do Finora:
- `data/` ao lado do programa — do executável empacotado ou, em desenvolvimento, da raiz do projeto;
- no macOS empacotado, `~/SuperFastFiles/data` (o .app não pode guardar dados dentro dele);
- se a pasta do programa não permitir gravar, `~/SuperFastFiles/data`, com aviso;
- a variável de ambiente SFF_DATA_DIR força outra pasta (testes, uso avançado).
"""
import os
import sys
import tempfile
from pathlib import Path

HOME_FOLDER = "SuperFastFiles"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):              # executável gerado pelo PyInstaller
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]     # desenvolvimento: raiz do projeto


def home_data_dir() -> Path:
    return Path.home() / HOME_FOLDER / "data"


def writable(folder: Path) -> bool:
    """Cria a pasta (se preciso) e testa gravar um arquivo nela."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".teste-", delete=True):
            pass
        return True
    except OSError:
        return False


def choose_data_dir(app: Path | None = None, platform: str | None = None, frozen: bool | None = None,
                    env: dict | None = None) -> tuple[Path, Path | None]:
    """(pasta de dados, pasta do programa que não deixou gravar — para avisar o usuário — ou None)."""
    env = os.environ if env is None else env
    platform = platform or sys.platform
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if env.get("SFF_DATA_DIR"):
        return Path(env["SFF_DATA_DIR"]), None
    if platform == "darwin" and frozen:
        return home_data_dir(), None
    candidate = (app or app_dir()) / "data"
    if writable(candidate):
        return candidate, None
    return home_data_dir(), candidate.parent


DATA_DIR, BLOCKED_DIR = choose_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)


def data_notice() -> str | None:
    """Aviso (no idioma ativo) quando os dados não puderam ficar ao lado do programa."""
    if BLOCKED_DIR is None:
        return None
    from superfastfiles.i18n import tr
    return tr("A pasta do programa ({blocked}) não permite gravar dados.\n"
              "Suas preferências e o histórico vão ficar em {folder}.", blocked=BLOCKED_DIR, folder=DATA_DIR)
