"""Gera o pacote portátil do SuperFastFiles para o sistema atual (Windows, Linux ou macOS).

    python tools/build.py

Resultado em dist/: a pasta SuperFastFiles (SuperFastFiles + sff) e SuperFastFiles-<versão>-<sistema>.zip/.tar.gz.
Antes de compactar, roda o executável com --teste numa pasta de dados vazia e a CLI numa cópia de verdade:
se algo faltar no pacote, o build falha.
"""
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from superfastfiles import __version__  # noqa: E402

DIST = ROOT / "dist"
PKG = DIST / "SuperFastFiles"
SYSTEM = {"win32": "windows", "linux": "linux", "darwin": "macos"}.get(sys.platform, sys.platform)
EXE = ".exe" if sys.platform == "win32" else ""


def make_icon() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QApplication
    import qtawesome as qta
    app = QApplication.instance() or QApplication([])
    from superfastfiles.ui import theme
    from superfastfiles.ui.main_window import APP_ICON
    icon = qta.icon(APP_ICON, color=theme.LIGHT["acc"])
    out = ROOT / "packaging"
    if sys.platform == "win32":
        icon.pixmap(QSize(256, 256)).toImage().save(str(out / "superfastfiles.ico"))
    icon.pixmap(QSize(256, 256)).toImage().save(str(out / "superfastfiles.png"))
    del app


def pyinstaller() -> None:
    shutil.rmtree(PKG, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(DIST),
                    "--workpath", str(ROOT / "build"), str(ROOT / "packaging" / "superfastfiles.spec")], check=True)


def smoke_test() -> None:
    with tempfile.TemporaryDirectory() as data:
        env = dict(os.environ, SFF_DATA_DIR=data, QT_QPA_PLATFORM="offscreen")
        r = subprocess.run([str(PKG / f"SuperFastFiles{EXE}"), "--teste"], env=env, timeout=180)
        if r.returncode != 0:
            sys.exit(f"O executável falhou no teste (código {r.returncode}).")
        src = Path(data) / "origem"
        src.mkdir()
        (src / "x.bin").write_bytes(os.urandom(5 << 20))
        r = subprocess.run([str(PKG / f"sff{EXE}"), "copy", str(src), str(Path(data) / "destino"), "--verify", "-q"],
                           env=env, timeout=120)
        if r.returncode != 0 or (Path(data) / "destino" / "origem" / "x.bin").read_bytes() != (src / "x.bin").read_bytes():
            sys.exit(f"A linha de comando (sff) falhou no teste (código {r.returncode}).")
    if (PKG / "data").exists():
        shutil.rmtree(PKG / "data")
    print("Teste dos executáveis: OK")


def archive() -> Path:
    name = f"SuperFastFiles-{__version__}-{SYSTEM}"
    if sys.platform == "win32":
        out = DIST / f"{name}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for f in PKG.rglob("*"):
                z.write(f, Path("SuperFastFiles") / f.relative_to(PKG))
    else:
        out = DIST / f"{name}.tar.gz"
        with tarfile.open(out, "w:gz") as t:
            t.add(PKG, arcname="SuperFastFiles")
    return out


def size(path: Path) -> str:
    total = path.stat().st_size if path.is_file() else sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return f"{total / 1024 / 1024:.0f} MB"


if __name__ == "__main__":
    make_icon()
    pyinstaller()
    smoke_test()
    out = archive()
    print(f"Pasta: {PKG} ({size(PKG)})\nPacote: {out} ({size(out)})")
