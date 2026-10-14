import sys

from superfastfiles import APP_NAME


def _setup_app(argv):
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication
    from superfastfiles.core import settings
    from superfastfiles.ui import fonts, locale_br, theme
    app = QApplication(argv)
    app.setOrganizationName(settings.ORG)
    app.setApplicationName(settings.APP)
    app.setStyle("Fusion")
    loaded = fonts.load()
    ok_tr = locale_br.install(app)
    font = QFont()
    font.setFamilies(theme.FONT_UI)
    font.setPointSize(theme.FONT_PT)
    app.setFont(font)
    return app, loaded, ok_tr


def smoke_test() -> int:
    """`SuperFastFiles --teste`: confere o pacote sem mostrar nada (fontes, tradução, motor, janela) e sai."""
    import os
    import tempfile
    from pathlib import Path
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from superfastfiles import __version__
    from superfastfiles.engine import JobSpec, Mode, Runner
    app, loaded, ok_tr = _setup_app(sys.argv)
    problems = []
    if not {"IBM Plex Sans", "IBM Plex Mono"} <= loaded:
        problems.append("fontes IBM Plex")
    if not ok_tr:
        problems.append("tradução pt-BR do Qt")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "origem"
        (src / "sub").mkdir(parents=True)
        (src / "a.txt").write_bytes(b"teste")
        (src / "sub" / "b.bin").write_bytes(os.urandom(3 << 20))
        r = Runner(JobSpec(mode=Mode.COPY, sources=[str(src)], dest=str(Path(tmp) / "destino"), verify=True))
        r.run()
        if r.stats.errors or (Path(tmp) / "destino" / "origem" / "sub" / "b.bin").read_bytes() != \
                (src / "sub" / "b.bin").read_bytes():
            problems.append("motor de cópia")
    from superfastfiles.ui.main_window import KEYS, MainWindow
    w = MainWindow()
    for key in KEYS:
        w.go_to(key)
    w.toggle_theme()
    w.toggle_theme()
    QTimer.singleShot(300, app.quit)
    app.exec()
    print(f"{APP_NAME} {__version__}: " + ("OK" if not problems else "PROBLEMAS: " + ", ".join(problems)))
    return 1 if problems else 0


def main():
    if "--teste" in sys.argv:
        return smoke_test()
    if len(sys.argv) > 1 and sys.argv[1] in ("copy", "move", "sync", "delete", "--version"):
        from superfastfiles.cli import main as cli_main
        return cli_main(sys.argv[1:])

    from PySide6.QtCore import qInstallMessageHandler
    from PySide6.QtWidgets import QMessageBox
    from superfastfiles.core import logs, paths, single_instance
    from superfastfiles.ui.error_dialog import show_error
    logs.setup()
    logs.session_start(paths.DATA_DIR)
    app, loaded, ok_tr = _setup_app(sys.argv)
    name = single_instance.name_for(paths.DATA_DIR)
    if single_instance.already_running(name):
        logs.log.info("Já estava aberto; só trouxe a janela para a frente")
        return 0
    single_instance.listen(name)
    qInstallMessageHandler(logs.qt_message_handler)
    logs.set_error_handler(show_error)
    if not {"IBM Plex Sans", "IBM Plex Mono"} <= loaded:
        logs.log.warning("Fontes IBM Plex não carregadas; usando as do sistema")
    if not ok_tr:
        logs.log.warning("Tradução pt-BR do Qt não encontrada")
    if paths.DATA_NOTICE:
        QMessageBox.information(None, "Onde ficam seus dados", paths.DATA_NOTICE)
    from superfastfiles.ui.main_window import MainWindow
    w = MainWindow()
    single_instance.window = w
    # Origens passadas na linha de comando (ex.: "Enviar para" do Explorer)
    extra = [a for a in sys.argv[1:] if not a.startswith("-")]
    if extra:
        w.pages["copy"].sources.add_paths(extra)
    w.show()
    code = app.exec()
    logs.log.info("App fechado")
    return code


if __name__ == "__main__":
    sys.exit(main())
