"""Janela principal no padrão do Finora: barra lateral, cabeçalho, páginas num QStackedWidget, barra de status."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton, QScrollArea,
    QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)
import qtawesome as qta

from superfastfiles import APP_NAME, __version__, format as fmt
from superfastfiles.core import settings
from superfastfiles.core.paths import DATA_DIR
from superfastfiles.engine.job import MODE_LABELS
from superfastfiles.services import jobs
from superfastfiles.ui import theme
from superfastfiles.ui.copy_page import CopyPage
from superfastfiles.ui.engine_bridge import JobController
from superfastfiles.ui.other_pages import HistoryPage, LogPage, QueuePage, SettingsPage
from superfastfiles.ui.widgets import retheme

APP_ICON = "fa6s.bolt"

# (chave, ícone, rótulo, subtítulo do cabeçalho). Use as chaves, não a posição.
NAV = [
    ("copy", "fa6s.copy", "Copiar", "Copiar, mover, sincronizar ou apagar"),
    ("queue", "fa6s.list-check", "Fila", "Tarefas esperando para rodar em sequência"),
    ("history", "fa6s.clock-rotate-left", "Histórico", "O que já foi feito, com tempo e velocidade"),
    ("log", "fa6s.file-lines", "Log", "Detalhes e erros da última tarefa"),
    ("settings", "fa6s.gear", "Configurações", "Aparência e desempenho"),
]
KEYS = [n[0] for n in NAV]


class Sidebar(QWidget):
    """Menu à esquerda. Modo 'sidebar' (ícone + nome, 200px) ou 'rail' (só ícones, 52px)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFixedWidth(200)
        self.mode = "sidebar"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP_M, 10, theme.SP_M, 0)
        lay.setSpacing(2)

        brand = QFrame(objectName="brand")
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(theme.SP_M, theme.SP_M, theme.SP_M, theme.SP_M)
        bl.setSpacing(theme.SP_M)
        self._brand_icon = QLabel()
        self._names = QWidget()
        names = QVBoxLayout(self._names)
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(0)
        names.addWidget(QLabel(APP_NAME, objectName="brandName"))
        names.addWidget(QLabel("Copiador rápido", objectName="brandSub"))
        bl.addWidget(self._brand_icon)
        bl.addWidget(self._names, 1)
        self._brand_layout = bl
        lay.addWidget(brand)
        lay.addSpacing(10)

        nav = QWidget(objectName="navList")
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(2)
        scroll = QScrollArea(objectName="navScroll", widgetResizable=True, frameShape=QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(nav)
        self.group = QButtonGroup(self, exclusive=True)
        self.buttons = []
        for i, (_key, icon, label, _sub) in enumerate(NAV):
            b = QPushButton(label, objectName="navItem", checkable=True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIconSize(QSize(14, 14))
            b.setToolTip(f"{label} (Ctrl+{i + 1})")
            self.group.addButton(b, i)
            self.buttons.append((b, icon, label))
            nl.addWidget(b)
        self.queue_badge = None
        nl.addStretch(1)
        lay.addWidget(scroll, 1)

        self.theme_btn = QPushButton(objectName="themeToggle")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setIconSize(QSize(14, 14))
        self.collapse_btn = QPushButton(objectName="themeToggle")
        self.collapse_btn.setCursor(Qt.PointingHandCursor)
        self.collapse_btn.setIconSize(QSize(14, 14))
        self._bottom = QHBoxLayout()
        self._bottom.setContentsMargins(0, 0, 0, 0)
        self._bottom.setSpacing(0)
        self._bottom.addWidget(self.theme_btn, 1)
        self._bottom.addWidget(self.collapse_btn)
        lay.addLayout(self._bottom)
        self._lay = lay
        self._dark = False

    def set_mode(self, mode: str):
        self.mode = mode
        rail = mode == "rail"
        self.setProperty("mode", mode)
        self.setFixedWidth(52 if rail else 200)
        self._lay.setContentsMargins(*((6, 10, 6, 0) if rail else (theme.SP_M, 10, theme.SP_M, 0)))
        self._names.setVisible(not rail)
        self._brand_layout.setContentsMargins(*((0, 6, 0, 6) if rail else (theme.SP_M,) * 4))
        self._brand_layout.setAlignment(self._brand_icon, Qt.AlignCenter if rail else Qt.AlignLeft)
        for b, _icon, label in self.buttons:
            b.setText("" if rail else label)
        self._theme_text()
        for w in [self] + self.findChildren(QPushButton):
            w.style().unpolish(w)
            w.style().polish(w)

    def set_queue_count(self, n: int):
        b, _icon, label = self.buttons[KEYS.index("queue")]
        b.setText("" if self.mode == "rail" else (f"{label}  ({n})" if n else label))

    def _theme_text(self):
        rail = self.mode == "rail"
        self.theme_btn.setText("" if rail else ("Tema claro" if self._dark else "Tema escuro"))
        self.collapse_btn.setToolTip("Mostrar o menu com nomes" if rail else "Recolher o menu (só ícones)")
        self._bottom.setDirection(QHBoxLayout.TopToBottom if rail else QHBoxLayout.LeftToRight)
        if hasattr(self, "_t"):
            self.collapse_btn.setIcon(qta.icon("fa6s.angles-right" if rail else "fa6s.angles-left",
                                               color=self._t["mut"], color_active=self._t["fg"]))

    def apply_theme(self, name: str, t: dict):
        self._t = t
        self._brand_icon.setPixmap(qta.icon(APP_ICON, color=t["acc"]).pixmap(QSize(16, 16)))
        for b, icon, _label in self.buttons:
            b.setIcon(qta.icon(icon, color=t["mut"], color_active=t["fg"], color_on=t["fg"]))
        self._dark = name == "dark"
        self._theme_text()
        self.theme_btn.setIcon(qta.icon("fa6s.sun" if self._dark else "fa6s.moon", color=t["mut"],
                                        color_active=t["fg"]))
        self.theme_btn.setToolTip("Alternar entre tema claro e escuro (Ctrl+T)")


class Header(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("header")
        self.setFixedHeight(44)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(theme.SP_L)
        self.title = QLabel(objectName="pageTitle")
        self.subtitle = QLabel(objectName="pageSubtitle")
        self.subtitle.setMinimumWidth(1)
        self.status = QLabel()
        self.status.setProperty("role", "muted")
        lay.addWidget(self.title)
        lay.addWidget(self.subtitle, 1)
        lay.addWidget(self.status)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.quitting = False
        self.running_queue = False
        self.setWindowTitle(f"{APP_NAME} — copiador de arquivos")
        self.setMinimumSize(860, 560)
        self.setAcceptDrops(True)
        geo = settings.get_geometry()
        if geo is None or not self.restoreGeometry(geo):
            self._fit_to_screen()

        self.theme_name = settings.get_theme(theme.DEFAULT_THEME)
        t = theme.tokens(self.theme_name)
        self.ctl = JobController(self)
        self.sidebar = Sidebar()
        self.header = Header()
        self.stack = QStackedWidget()
        self.pages = {
            "copy": CopyPage(t, self.ctl),
            "queue": QueuePage(t),
            "history": HistoryPage(t),
            "log": LogPage(t),
            "settings": SettingsPage(t),
        }
        for key in KEYS:
            p = self.pages[key]
            self.stack.addWidget(p)
            p.message.connect(lambda m: self.statusBar().showMessage(m, 4000))

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self.header)
        rl.addWidget(self.stack, 1)
        central = QWidget()
        cl = QHBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.sidebar)
        cl.addWidget(right, 1)
        self.setCentralWidget(central)
        self._build_statusbar()

        self.sidebar.group.idClicked.connect(self.go_to)
        self.sidebar.theme_btn.clicked.connect(self.toggle_theme)
        self.sidebar.collapse_btn.clicked.connect(
            lambda: self.set_nav("sidebar" if self.sidebar.mode == "rail" else "rail"))
        copy, queue = self.pages["copy"], self.pages["queue"]
        copy.enqueue.connect(self.enqueue)
        queue.run_queue.connect(self.run_queue)
        queue.edit_job.connect(self._edit_job)
        self.pages["settings"].theme_changed.connect(self.set_theme)
        self.ctl.tick.connect(self._on_tick)
        self.ctl.finished.connect(self._on_finished)
        for i in range(len(NAV)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self.go_to(i))
        QShortcut(QKeySequence("Ctrl+T"), self, activated=self.toggle_theme)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=lambda: (self.go_to("copy"), copy.start()))

        self._build_tray()
        self.apply_theme(self.theme_name)
        self.sidebar.set_mode(settings.get_nav())
        self.sidebar.set_queue_count(len(jobs.queue()))
        self.go_to("copy")

    # Navegação ---------------------------------------------------------------------
    def page(self, key: str) -> QWidget:
        return self.pages[key]

    def go_to(self, where: str | int):
        index = KEYS.index(where) if isinstance(where, str) else where
        key, _icon, label, subtitle = NAV[index]
        page = self.pages[key]
        if hasattr(page, "refresh"):
            page.refresh()
        self.stack.setCurrentIndex(index)
        self.sidebar.group.button(index).setChecked(True)
        self.header.title.setText(label)
        self.header.subtitle.setText(subtitle)

    def set_nav(self, mode: str):
        self.sidebar.set_mode(mode)
        self.sidebar.set_queue_count(len(jobs.queue()))
        settings.set_nav(mode)

    def _fit_to_screen(self):
        area = self.screen().availableGeometry()
        w = min(1280, area.width() - 2 * theme.SP_L)
        h = min(820, area.height() - 2 * theme.SP_L)
        self.resize(w, h)
        self.move(area.x() + (area.width() - w) // 2, area.y() + (area.height() - h) // 2)

    def _build_statusbar(self):
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        sb.setFixedHeight(24)
        where = QLabel(f"Dados em {DATA_DIR}")
        sb.addWidget(where)
        sb.addPermanentWidget(QLabel(f"v{__version__}"))

    # Tema ------------------------------------------------------------------------------
    def apply_theme(self, name: str):
        self.theme_name = name
        t = theme.apply(QApplication.instance(), name)
        self.setWindowIcon(qta.icon(APP_ICON, color=t["acc"]))
        if self.tray is not None:
            self.tray.setIcon(self.windowIcon())
        self.sidebar.apply_theme(name, t)
        for p in self.pages.values():
            p.apply_theme(t)
        retheme(self, t)
        self.pages["settings"].set_theme_name(name)

    def toggle_theme(self):
        self.set_theme("light" if self.theme_name == "dark" else "dark")

    def set_theme(self, name: str):
        self.apply_theme(name)
        settings.set_theme(name)
        self.statusBar().showMessage("Tema claro ativado" if name == "light" else "Tema escuro ativado", 2500)

    # Arrastar arquivos para qualquer lugar da janela = origens -----------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.go_to("copy")
            self.pages["copy"].sources.add_paths(paths)

    # Fila --------------------------------------------------------------------------------
    def enqueue(self, spec):
        n = jobs.enqueue(spec)
        self.sidebar.set_queue_count(n)
        self.statusBar().showMessage(f"Tarefa posta na fila ({n} esperando)", 3000)

    def _edit_job(self, spec):
        self.pages["copy"].load_spec(spec)
        self.sidebar.set_queue_count(len(jobs.queue()))
        self.go_to("copy")

    def run_queue(self):
        if self.ctl.busy:
            self.statusBar().showMessage("Espere a tarefa atual terminar", 3000)
            return
        self.running_queue = True
        self._next_in_queue()

    def _next_in_queue(self):
        spec = jobs.pop_queue()
        self.sidebar.set_queue_count(len(jobs.queue()))
        self.pages["queue"].refresh()
        if spec is None:
            self.running_queue = False
            return
        self.go_to("copy")
        self.pages["copy"].start(spec=spec, ask=False)

    # Andamento ----------------------------------------------------------------------------
    def _on_tick(self, s: dict):
        pct = f"{100 * s['done_bytes'] / s['scan_bytes']:.0f}% · " if s["scan_bytes"] and not s["scanning"] else ""
        txt = f"{pct}{fmt.speed(s['speed'])}"
        self.header.status.setText(("Pausado · " if s.get("paused") else "") + txt)
        self.setWindowTitle(f"{pct}{APP_NAME}")

    def _on_finished(self, runner, snap: dict, error: str):
        self.header.status.setText("")
        self.setWindowTitle(f"{APP_NAME} — copiador de arquivos")
        if error:
            self.running_queue = False
            return
        jobs.add_history(runner.spec, snap, runner.cancelled, runner.stats.errors)
        self.pages["log"].show_runner(runner, snap)
        msg = (f"{MODE_LABELS[runner.spec.mode]}: {fmt.count(snap['done_files'])} arquivos, "
               f"{fmt.size(snap['done_bytes'])} em {fmt.duration(snap['elapsed'])} "
               f"({fmt.speed(snap['avg_speed'])})" + (f" · {snap['errors']} erro(s)" if snap["errors"] else ""))
        self.statusBar().showMessage(msg, 15000)
        if not self.isActiveWindow() and self.tray is not None and settings.get_tray() and not runner.spec.dry_run:
            self.tray.show()
            self.tray.showMessage(APP_NAME, ("Cancelado — " if runner.cancelled else "Concluído — ") + msg,
                                  QSystemTrayIcon.Warning if snap["errors"] else QSystemTrayIcon.Information, 8000)
        if self.running_queue and not runner.cancelled:
            self._next_in_queue()
        else:
            self.running_queue = False

    # Bandeja ------------------------------------------------------------------------------
    def _build_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu(self)
        menu.addAction("Abrir", self._show)
        menu.addAction("Sair", self._quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self._show() if r in (QSystemTrayIcon.Trigger,
                                                                     QSystemTrayIcon.DoubleClick) else None)
        self.tray.messageClicked.connect(self._show)

    def _show(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self):
        self.quitting = True
        self.close()

    def closeEvent(self, event):
        if self.ctl.busy:
            from PySide6.QtWidgets import QMessageBox
            if QMessageBox.question(self, "Tarefa em andamento", "Uma tarefa ainda está rodando. Cancelar e "
                                    "fechar?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                event.ignore()
                return
            self.ctl.cancel()
            if self.ctl._thread is not None:
                self.ctl._thread.join(10)
        settings.set_geometry(self.saveGeometry())
        if self.tray is not None:
            self.tray.hide()
        super().closeEvent(event)
