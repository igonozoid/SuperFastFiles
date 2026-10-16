# PyInstaller: pacote portátil do SuperFastFiles (uma pasta; os dados ficam em data/ ao lado).
# Dois executáveis na mesma pasta: SuperFastFiles (janela) e sff (linha de comando, com console).
# Gere com:  python tools/build.py
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src" / "superfastfiles"
ICON = ROOT / "packaging" / ("superfastfiles.ico" if sys.platform == "win32" else "superfastfiles.png")

datas = [(str(SRC / "assets"), "superfastfiles/assets")]      # fontes IBM Plex + licença OFL
datas += collect_data_files("qtawesome")
hidden = collect_submodules("superfastfiles") + ["xxhash"]

# Partes do Qt que o app não usa (pacote bem menor) — mesma lista do Finora, mais QtCharts/QtPrintSupport
excludes = ["tkinter", "pytest", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
            "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DExtras", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
            "PySide6.Qt3DAnimation", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
            "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtBluetooth",
            "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort",
            "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtDesigner", "PySide6.QtHelp",
            "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech",
            "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtNfc", "PySide6.QtSql", "PySide6.QtTest",
            "PySide6.QtXml", "PySide6.QtHttpServer", "PySide6.QtPdfWidgets", "PySide6.QtPdf", "PySide6.QtCharts",
            "PySide6.QtPrintSupport", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSvgWidgets"]

gui = Analysis([str(ROOT / "packaging" / "launcher.py")], pathex=[str(ROOT / "src")], datas=datas,
               hiddenimports=hidden, excludes=excludes, noarchive=False)
cli = Analysis([str(ROOT / "packaging" / "cli_launcher.py")], pathex=[str(ROOT / "src")],
               hiddenimports=["xxhash"], excludes=excludes + ["PySide6", "qtawesome"], noarchive=False)
DROP = ("opengl32sw", "qt6quick", "qt6qml", "qt6pdf", "qt6virtualkeyboard")
gui.binaries = [b for b in gui.binaries if not Path(b[0]).name.lower().removeprefix("lib").startswith(DROP)]

icon = str(ICON) if ICON.exists() else None
gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name="SuperFastFiles", console=False,
              icon=icon, upx=False)
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name="sff", console=True, icon=icon, upx=False)
coll = COLLECT(gui_exe, gui.binaries, gui.datas, cli_exe, cli.binaries, cli.datas, name="SuperFastFiles", upx=False)

# macOS: aplicativo .app de verdade (o que o usuário arrasta para Aplicativos). O sff vai dentro, em
# SuperFastFiles.app/Contents/MacOS/sff. O ícone PNG vira .icns pelo Pillow.
if sys.platform == "darwin":
    version = next(line.split('"')[1] for line in (SRC / "__init__.py").read_text().splitlines()
                   if line.startswith("__version__"))
    app = BUNDLE(coll, name="SuperFastFiles.app", icon=icon, bundle_identifier="br.com.ignf.superfastfiles",
                 info_plist={"CFBundleName": "SuperFastFiles", "CFBundleDisplayName": "SuperFastFiles",
                             "CFBundleShortVersionString": version, "CFBundleVersion": version,
                             "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0"})
