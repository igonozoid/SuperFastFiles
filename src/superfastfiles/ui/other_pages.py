"""Fila, Histórico, Log e Configurações."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QSpinBox, QVBoxLayout, QWidget,
)

from superfastfiles import APP_NAME, __version__, format as fmt
from superfastfiles.core import settings
from superfastfiles.core.paths import DATA_DIR
from superfastfiles.engine.job import MODE_LABELS, Mode
from superfastfiles.engine.verify import ALGORITHM
from superfastfiles.services import jobs
from superfastfiles.ui import theme
from superfastfiles.ui.tables import RowsModel, make_table
from superfastfiles.ui.theme import SP_L, SP_M, SP_S
from superfastfiles.ui.widgets import button, field_label, help_icon, page_scroll, section


def _body(widget: QWidget) -> QVBoxLayout:
    lay = QVBoxLayout(widget)
    lay.setContentsMargins(16, SP_L, 16, 16)
    lay.setSpacing(SP_M)
    return lay


def _empty(text: str) -> QFrame:
    box = QFrame(objectName="emptyCard")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(SP_L * 2, SP_L * 2, SP_L * 2, SP_L * 2)
    lbl = QLabel(text, objectName="emptyText", wordWrap=True, alignment=Qt.AlignCenter)
    lay.addWidget(lbl)
    return box


class QueuePage(QWidget):
    message = Signal(str)
    run_queue = Signal()
    edit_job = Signal(object)

    def __init__(self, t: dict):
        super().__init__()
        lay = _body(self)
        top = QHBoxLayout()
        info = QLabel("Tarefas guardadas com “Pôr na fila”. Rodam uma depois da outra, sem precisar de você.")
        info.setProperty("role", "muted")
        top.addWidget(info, 1)
        self.edit_btn = button("Abrir na tela Copiar", "secondary", t, "fa6s.pen")
        self.edit_btn.clicked.connect(self._edit)
        self.rm_btn = button("Remover", "secondary", t, "fa6s.minus")
        self.rm_btn.clicked.connect(self._remove)
        self.run_btn = button("Executar a fila", "primary")
        self.run_btn.clicked.connect(self.run_queue.emit)
        for w in (self.edit_btn, self.rm_btn, self.run_btn):
            top.addWidget(w)
        lay.addLayout(top)
        self.model = RowsModel(["#", "Modo", "Origem", "Destino", "Opções"], mono={0}, right={0})
        self.view = make_table(self.model, 2, {0: 40, 1: 100, 3: 260, 4: 200})
        lay.addWidget(self.view, 1)
        self.empty = _empty("A fila está vazia. Na tela Copiar, monte uma tarefa e clique em “Pôr na fila”.")
        lay.addWidget(self.empty)
        self.refresh()

    def refresh(self):
        q = jobs.queue()
        rows = []
        for i, s in enumerate(q, 1):
            opts = [s.overwrite.value] if s.mode != Mode.DELETE else []
            if s.verify:
                opts.append("verificar")
            if s.include or s.exclude:
                opts.append("filtros")
            rows.append([i, MODE_LABELS[s.mode], "; ".join(s.sources), s.dest or "—", ", ".join(opts)])
        self.model.set_rows(rows, q)
        self.view.setVisible(bool(q))
        self.empty.setVisible(not q)
        self.run_btn.setEnabled(bool(q))
        self.rm_btn.setEnabled(bool(q))
        self.edit_btn.setEnabled(bool(q))

    def _selected(self) -> list[int]:
        return sorted({i.row() for i in self.view.selectionModel().selectedRows()})

    def _remove(self):
        rows = self._selected()
        if not rows:
            return
        q = jobs.queue()
        jobs.set_queue([s for i, s in enumerate(q) if i not in rows])
        self.refresh()

    def _edit(self):
        rows = self._selected()
        if rows:
            q = jobs.queue()
            spec = q.pop(rows[0])
            jobs.set_queue(q)
            self.refresh()
            self.edit_job.emit(spec)

    def apply_theme(self, t):
        pass


class HistoryPage(QWidget):
    message = Signal(str)

    def __init__(self, t: dict):
        super().__init__()
        lay = _body(self)
        top = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setProperty("role", "muted")
        top.addWidget(self.summary, 1)
        clear = button("Limpar histórico", "secondary", t, "fa6s.broom")
        clear.clicked.connect(self._clear)
        top.addWidget(clear)
        lay.addLayout(top)
        self.model = RowsModel(["Quando", "Modo", "Origem → destino", "Arquivos", "Dados", "Tempo", "Velocidade",
                                "Erros"], mono={3, 4, 5, 6, 7}, right={3, 4, 5, 6, 7})
        self.view = make_table(self.model, 2, {0: 120, 1: 90, 3: 80, 4: 90, 5: 70, 6: 100, 7: 50})
        self.view.doubleClicked.connect(self._details)
        lay.addWidget(self.view, 1)
        self.empty = _empty("Nenhuma tarefa ainda. Cada cópia terminada aparece aqui, com tempo e velocidade.")
        lay.addWidget(self.empty)
        self.refresh()

    def refresh(self):
        items = jobs.history()
        rows, tones = [], []
        for h in items:
            mode = MODE_LABELS.get(Mode(h.mode), h.mode) + (" (simulação)" if h.dry_run else "")
            where = "; ".join(h.sources) + (f" → {h.dest}" if h.dest else "")
            rows.append([time.strftime("%d/%m/%Y %H:%M", time.localtime(h.when)), mode, where, fmt.count(h.files),
                         fmt.size(h.bytes), fmt.duration(h.seconds), fmt.speed(h.speed), h.errors])
            tones.append("neg" if h.errors or h.cancelled else None)
        self.model.set_rows(rows, items, tones)
        self.view.setVisible(bool(items))
        self.empty.setVisible(not items)
        total = sum(h.bytes for h in items if not h.dry_run)
        self.summary.setText(f"{len(items)} tarefa(s) · {fmt.size(total)} copiados no total. "
                             "Dois cliques numa linha mostram os detalhes.")

    def _details(self, index):
        h = self.model.payload[index.row()]
        lines = [f"Modo: {h.mode}", f"Origem: {'; '.join(h.sources)}", f"Destino: {h.dest or '—'}",
                 f"Estratégia: {h.strategy or '—'}", f"Arquivos: {h.files} · pulados {h.skipped} · "
                 f"apagados {h.deleted}", f"Verificação: {'sim' if h.verified else 'não'}",
                 f"Cancelado: {'sim' if h.cancelled else 'não'}"]
        box = QMessageBox(self)
        box.setWindowTitle("Detalhes da tarefa")
        box.setText("\n".join(lines))
        if h.error_lines:
            box.setDetailedText("\n".join(h.error_lines))
        box.exec()

    def _clear(self):
        if QMessageBox.question(self, "Limpar histórico?", "Apagar a lista de tarefas já feitas? "
                                "Os arquivos não são afetados.") == QMessageBox.Yes:
            jobs.clear_history()
            self.refresh()

    def apply_theme(self, t):
        self.model.theme_name = settings.get_theme()


class LogPage(QWidget):
    message = Signal(str)

    def __init__(self, t: dict):
        super().__init__()
        lay = _body(self)
        top = QHBoxLayout()
        self.title = QLabel("Mensagens da última tarefa: estratégia usada, erros e itens ignorados.")
        self.title.setProperty("role", "muted")
        top.addWidget(self.title, 1)
        copy = button("Copiar", "secondary", t, "fa6s.copy")
        copy.clicked.connect(lambda: (QGuiApplication.clipboard().setText(self.text.toPlainText()),
                                      self.message.emit("Log copiado")))
        save = button("Salvar…", "secondary", t, "fa6s.floppy-disk")
        save.clicked.connect(self._save)
        top.addWidget(copy)
        top.addWidget(save)
        lay.addLayout(top)
        self.text = QPlainTextEdit(objectName="logView", readOnly=True)
        self.text.setFont(theme.mono_font())
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.setPlaceholderText("Nada por aqui ainda.")
        lay.addWidget(self.text, 1)

    def show_runner(self, runner, snap: dict):
        lines = [f"{time.strftime('%d/%m/%Y %H:%M:%S')} · {MODE_LABELS[runner.spec.mode]}"
                 f"{' (simulação)' if runner.spec.dry_run else ''}",
                 f"Origem: {'; '.join(runner.spec.sources)}"]
        if runner.spec.dest:
            lines.append(f"Destino: {runner.spec.dest}")
        lines += list(runner.stats.log)
        lines.append(f"Resumo: {fmt.count(snap['done_files'])} arquivos, {fmt.size(snap['done_bytes'])} em "
                     f"{fmt.duration(snap['elapsed'])} ({fmt.speed(snap.get('avg_speed', 0))}); pulados "
                     f"{fmt.count(snap['skipped_files'])}; apagados {fmt.count(snap['deleted_files'])}; "
                     f"erros {snap['errors']}")
        self.text.setPlainText("\n".join(lines))

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Salvar log", "superfastfiles-log.txt", "Texto (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text.toPlainText())
            self.message.emit(f"Log salvo em {path}")

    def apply_theme(self, t):
        pass


class SettingsPage(QWidget):
    message = Signal(str)
    theme_changed = Signal(str)
    nav_changed = Signal(str)

    def __init__(self, t: dict):
        super().__init__()
        lay = page_scroll(self)

        look, ll = section("Aparência", "fa6s.palette", t)
        row = QHBoxLayout()
        row.setSpacing(0)
        self.theme_group = QButtonGroup(self, exclusive=True)
        for i, (key, label) in enumerate((("light", "Claro"), ("dark", "Escuro"))):
            b = button(label, "seg", t, "fa6s.sun" if key == "light" else "fa6s.moon")
            b.setCheckable(True)
            b.setMinimumWidth(90)
            b.setProperty("pos", "first" if i == 0 else "last")
            b.setProperty("key", key)
            self.theme_group.addButton(b, i)
            row.addWidget(b)
        self.theme_group.idClicked.connect(lambda i: self.theme_changed.emit(("light", "dark")[i]))
        row.addStretch(1)
        ll.addWidget(field_label("Tema (Ctrl+T)", t))
        ll.addLayout(row)
        self.tray = QCheckBox("Avisar ao lado do relógio quando uma tarefa terminar")
        self.tray.setChecked(settings.get_tray())
        self.tray.toggled.connect(settings.set_tray)
        ll.addWidget(self.tray)
        lay.addWidget(look)

        perf, pl = section("Desempenho", "fa6s.bolt", t)
        note = QLabel("No automático, o SuperFastFiles olha se origem e destino são SSD, HDD, rede ou o mesmo disco "
                      "e escolhe threads e tamanho de bloco sozinho. Mude só se souber o que está fazendo.",
                      wordWrap=True)
        note.setProperty("role", "muted")
        pl.addWidget(note)
        grid = QGridLayout()
        grid.setHorizontalSpacing(SP_L)
        grid.setVerticalSpacing(SP_S)
        self.disk = QComboBox()
        for key, label in (("auto", "Automático"), ("ssd", "SSD/NVMe (muitas threads)"),
                           ("hdd", "Disco rígido (poucas threads)"), ("same", "Mesmo disco (sequencial)"),
                           ("net", "Rede")):
            self.disk.addItem(label, key)
        self.disk.setCurrentIndex(max(0, self.disk.findData(settings.get_disk_mode())))
        self.disk.currentIndexChanged.connect(lambda: settings.set_disk_mode(self.disk.currentData()))
        grid.addWidget(field_label("Tipo de disco", t, "Define a estratégia. Em HDD, ler e gravar ao mesmo tempo "
                                                      "no mesmo disco é lento; em SSD, quanto mais paralelo melhor."),
                       0, 0)
        grid.addWidget(self.disk, 1, 0)
        self.threads = QSpinBox(minimum=0, maximum=128)
        self.threads.setSpecialValueText("Automático")
        self.threads.setValue(settings.get_threads())
        self.threads.valueChanged.connect(settings.set_threads)
        grid.addWidget(field_label("Threads (arquivos pequenos)", t, "Quantos arquivos são copiados ao mesmo "
                                                                     "tempo. 0 = automático."), 0, 1)
        grid.addWidget(self.threads, 1, 1)
        self.buffer = QSpinBox(minimum=0, maximum=512, suffix=" MB")
        self.buffer.setSpecialValueText("Automático")
        self.buffer.setValue(settings.get_buffer_mb())
        self.buffer.valueChanged.connect(settings.set_buffer_mb)
        grid.addWidget(field_label("Tamanho do bloco", t, "Quanto é lido/gravado por vez nos arquivos grandes. "
                                                          "0 = automático (8 MB em SSD, 32 MB no mesmo HDD)."), 0, 2)
        grid.addWidget(self.buffer, 1, 2)
        pl.addLayout(grid)
        r1 = QHBoxLayout()
        self.unbuf = QCheckBox("Não usar o cache do sistema nos arquivos grandes")
        self.unbuf.setChecked(settings.get_unbuffered())
        self.unbuf.toggled.connect(settings.set_unbuffered)
        r1.addWidget(self.unbuf)
        r1.addWidget(help_icon("Como o FastCopy: arquivos grandes (32 MB ou mais) vão direto do disco para o disco, "
                               "sem encher a memória do sistema. Mantém o computador ágil durante cópias enormes "
                               "e costuma ser mais rápido.", t))
        r1.addStretch(1)
        pl.addLayout(r1)
        r2 = QHBoxLayout()
        self.native = QCheckBox("Usar a cópia do próprio sistema quando não houver verificação")
        self.native.setChecked(settings.get_native())
        self.native.toggled.connect(settings.set_native)
        r2.addWidget(self.native)
        r2.addWidget(help_icon("Windows: CopyFileEx (cópia no servidor em rede e block cloning no ReFS/Dev Drive). "
                               "Linux: reflink e copy_file_range. macOS: clonefile no APFS (instantâneo).", t))
        r2.addStretch(1)
        pl.addLayout(r2)
        lay.addWidget(perf)

        about, al = section("Sobre", "fa6s.circle-info", t)
        for text in (f"{APP_NAME} {__version__}", f"Verificação: {ALGORITHM}",
                     f"Preferências, histórico e log em: {DATA_DIR}"):
            lbl = QLabel(text, wordWrap=True)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            al.addWidget(lbl)
        lay.addWidget(about)
        lay.addStretch(1)

    def set_theme_name(self, name: str):
        self.theme_group.button(0 if name == "light" else 1).setChecked(True)

    def apply_theme(self, t):
        pass
