"""Tela principal: origens, destino, modo, opções e o andamento da cópia."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

import qtawesome as qta

from superfastfiles import format as fmt
from superfastfiles.core import settings
from superfastfiles.engine import JobSpec, Mode, Overwrite
from superfastfiles.engine.job import action_label, mode_label, overwrite_label
from superfastfiles.engine.verify import ALGORITHM
from superfastfiles.i18n import tr
from superfastfiles.ui import theme
from superfastfiles.ui.speed_chart import SpeedChart
from superfastfiles.ui.tables import RowsModel, make_table
from superfastfiles.ui.theme import SP_L, SP_M, SP_S
from superfastfiles.ui.widgets import KpiCard, _paint, button, field_label, help_icon, page_scroll, section, set_tone

def mode_help(m: Mode) -> str:
    return {
        Mode.COPY: tr("Copia para o destino. Nada é apagado; o que já está igual é pulado."),
        Mode.MOVE: tr("Copia e apaga da origem. No mesmo disco, só renomeia (instantâneo)."),
        Mode.SYNC: tr("Deixa o destino igual à origem: copia o que mudou e apaga do destino o que não existe mais "
                      "na origem."),
        Mode.DELETE: tr("Apaga as origens definitivamente (não vai para a Lixeira)."),
    }[m]


def run_label(m: Mode) -> str:
    return {Mode.COPY: tr("Copiar"), Mode.MOVE: tr("Mover"), Mode.SYNC: tr("Sincronizar"), Mode.DELETE: tr("Apagar")}[m]
MODE_ICONS = {Mode.COPY: "fa6s.copy", Mode.MOVE: "fa6s.right-from-bracket", Mode.SYNC: "fa6s.rotate",
              Mode.DELETE: "fa6s.trash-can"}


def _local_paths(mime) -> list[str]:
    return [u.toLocalFile() for u in mime.urls() if u.isLocalFile() and u.toLocalFile()] if mime.hasUrls() else []


class SourceList(QListWidget):
    """Lista de origens: aceita arquivos e pastas arrastados do Explorer/Finder."""
    changed = Signal()

    def __init__(self):
        super().__init__(objectName="sourceList")
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setMinimumHeight(130)
        self.setTextElideMode(Qt.ElideMiddle)

    def _hl(self, on: bool):
        self.setProperty("drop", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if _local_paths(e.mimeData()):
            e.acceptProposedAction()
            self._hl(True)

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._hl(False)

    def dropEvent(self, e):
        self._hl(False)
        self.add_paths(_local_paths(e.mimeData()))
        e.acceptProposedAction()

    def add_paths(self, paths):
        have = set(self.paths())
        for p in paths:
            p = os.path.normpath(p)
            if p not in have:
                it = QListWidgetItem(p)
                it.setToolTip(p)
                self.addItem(it)
                have.add(p)
        self.changed.emit()

    def paths(self) -> list[str]:
        return [self.item(i).text() for i in range(self.count())]

    def remove_selected(self):
        for it in self.selectedItems():
            self.takeItem(self.row(it))
        self.changed.emit()


class DropLineEdit(QLineEdit):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if _local_paths(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = _local_paths(e.mimeData())
        if paths:
            p = paths[0]
            self.setText(os.path.normpath(p if os.path.isdir(p) else os.path.dirname(p)))


class PlanDialog(QDialog):
    """Resultado da simulação: o que seria feito, sem ter feito nada."""

    def __init__(self, parent, plan, snap: dict):
        super().__init__(parent)
        self.setWindowTitle(tr("Simulação — nada foi alterado"))
        self.resize(900, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SP_L, SP_L, SP_L, SP_L)
        lay.setSpacing(SP_M)
        counts: dict[str, int] = {}
        for p in plan:
            counts[p.action] = counts.get(p.action, 0) + 1
        resumo = (" · ".join(f"{action_label(k)}: {fmt.count(v)}" for k, v in counts.items())
                  or tr("Nada a fazer: o destino já está igual."))
        lay.addWidget(QLabel(resumo, objectName="sectionTitle"))
        info = QLabel(tr("{size} seriam copiados. Pulados (iguais): {skipped}.", size=fmt.size(snap["scan_bytes"]),
                         skipped=fmt.count(snap["skipped_files"])))
        info.setProperty("role", "muted")
        lay.addWidget(info)
        model = RowsModel([tr("Ação"), tr("Caminho"), tr("Tamanho")], mono={2}, right={2})
        shown = plan[:50_000]
        tone = {"delete": "neg", "rmdir": "neg", "overwrite": "acc", "copy": "pos"}
        model.set_rows([[action_label(p.action), p.path, fmt.size(p.size) if p.size else ""] for p in shown],
                       tones=[tone.get(p.action) for p in shown])
        model.theme_name = settings.get_theme()
        lay.addWidget(make_table(model, 1, {0: 120, 2: 100}), 1)
        if len(plan) > len(shown):
            lay.addWidget(QLabel(tr("Mostrando os primeiros {shown} de {total}.", shown=fmt.count(len(shown)),
                                    total=fmt.count(len(plan)))))
        row = QHBoxLayout()
        row.addStretch(1)
        close = button(tr("Fechar"), "primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)


class CopyPage(QWidget):
    message = Signal(str)
    enqueue = Signal(object)          # JobSpec

    def __init__(self, t: dict, controller):
        super().__init__()
        self.t = t
        self.ctl = controller
        self.mode = Mode.COPY
        lay = page_scroll(self)

        # Modo -------------------------------------------------------------------
        mode_row = QHBoxLayout()
        mode_row.setSpacing(0)
        self.mode_group = QButtonGroup(self, exclusive=True)
        modes = list(Mode)
        for i, m in enumerate(modes):
            b = button(mode_label(m), "seg", t, MODE_ICONS[m])
            b.setCheckable(True)
            b.setMinimumWidth(110)
            b.setProperty("pos", "first" if i == 0 else "last" if i == len(modes) - 1 else "")
            self.mode_group.addButton(b, i)
            mode_row.addWidget(b)
        self.mode_group.idClicked.connect(lambda i: self.set_mode(modes[i]))
        mode_row.addSpacing(SP_L)
        self.mode_help = QLabel()
        self.mode_help.setProperty("role", "muted")
        self.mode_help.setWordWrap(True)
        mode_row.addWidget(self.mode_help, 1)
        lay.addLayout(mode_row)

        # Origem e destino ----------------------------------------------------------
        cols = QHBoxLayout()
        cols.setSpacing(SP_L)
        src_card, sl = section(tr("Origem"), "fa6s.folder-open", t)
        src_card.head.addWidget(help_icon(tr("Arraste arquivos e pastas para cá, ou use os botões.\n"
                                             "Cada pasta é copiada com o próprio nome dentro do destino."), t))
        self.sources = SourceList()
        self.sources.changed.connect(self._refresh_state)
        sl.addWidget(self.sources, 1)
        hint = QLabel(tr("Arraste arquivos e pastas para cá"))
        hint.setProperty("role", "field")
        sl.addWidget(hint)
        brow = QHBoxLayout()
        brow.setSpacing(SP_S)
        add_dir = button(tr("Pasta…"), "secondary", t, "fa6s.folder-plus")
        add_dir.clicked.connect(self._add_dir)
        add_files = button(tr("Arquivos…"), "secondary", t, "fa6s.file-circle-plus")
        add_files.clicked.connect(self._add_files)
        rem = button(tr("Remover"), "secondary", t, "fa6s.minus")
        rem.clicked.connect(self.sources.remove_selected)
        clear = button(tr("Limpar"), "link")
        clear.clicked.connect(lambda: (self.sources.clear(), self._refresh_state()))
        for w in (add_dir, add_files, rem):
            brow.addWidget(w)
        brow.addStretch(1)
        brow.addWidget(clear)
        sl.addLayout(brow)
        self.contents_only = QCheckBox(tr("Copiar só o conteúdo das pastas (sem criar a pasta no destino)"))
        sl.addWidget(self.contents_only)
        cols.addWidget(src_card, 3)

        right = QVBoxLayout()
        right.setSpacing(SP_L)
        self.dst_card, dl = section(tr("Destino"), "fa6s.hard-drive", t)
        drow = QHBoxLayout()
        drow.setSpacing(SP_S)
        self.dest = DropLineEdit()
        self.dest.setPlaceholderText(tr("Pasta de destino (arraste ou digite)"))
        self.dest.textChanged.connect(self._refresh_state)
        browse = button(tr("Procurar…"), "secondary", t, "fa6s.folder-open")
        browse.clicked.connect(self._browse_dest)
        drow.addWidget(self.dest, 1)
        drow.addWidget(browse)
        dl.addLayout(drow)
        right.addWidget(self.dst_card)

        opt_card, ol = section(tr("Opções"), "fa6s.sliders", t)
        grid = QGridLayout()
        grid.setHorizontalSpacing(SP_L)
        grid.setVerticalSpacing(SP_S)
        self.overwrite = QComboBox()
        for o in Overwrite:
            self.overwrite.addItem(overwrite_label(o), o.value)
        self.ow_label = field_label(tr("Quando o arquivo já existe no destino"), t,
                                    tr("Só os diferentes: compara tamanho e data de modificação (com 2 s de folga, "
                                       "por causa de pendrives FAT/exFAT)."))
        grid.addWidget(self.ow_label, 0, 0, 1, 2)
        grid.addWidget(self.overwrite, 1, 0, 1, 2)
        vrow = QHBoxLayout()
        vrow.setSpacing(SP_S)
        self.verify = QCheckBox(tr("Verificar depois de copiar"))
        vrow.addWidget(self.verify)
        vrow.addWidget(help_icon(tr("Relê cada arquivo gravado direto do disco (sem cache) e compara o hash "
                                    "{algorithm} com o da origem. Garante que a cópia está perfeita; "
                                    "leva mais tempo.", algorithm=ALGORITHM), t))
        vrow.addStretch(1)
        grid.addLayout(vrow, 2, 0, 1, 2)
        self.preserve = QCheckBox(tr("Manter as datas originais"))
        self.preserve.setChecked(True)
        grid.addWidget(self.preserve, 3, 0, 1, 2)
        xrow = QHBoxLayout()
        xrow.setSpacing(SP_S)
        self.extras = QCheckBox(tr("Modo servidor: copiar permissões e dados extras"))
        xrow.addWidget(self.extras)
        xrow.addWidget(help_icon(tr("Para servidores de arquivos e backups de empresa. Leva junto quem pode abrir "
                                    "cada arquivo e pasta (permissões/ACL) e os dados extras que o sistema guarda "
                                    "nos arquivos (fluxos alternativos no Windows, atributos estendidos no Linux e "
                                    "macOS).\nPara uso pessoal, deixe desligado. Copiar o dono original exige "
                                    "abrir o programa como administrador."), t))
        xrow.addStretch(1)
        grid.addLayout(xrow, 4, 0, 1, 2)
        ol.addLayout(grid)
        right.addWidget(opt_card)

        flt_card, fl = section(tr("Filtros"), "fa6s.filter", t)
        fl.addWidget(field_label(tr("Incluir só"), t, tr("Padrões separados por ponto e vírgula. Ex.: *.jpg; *.png\n"
                                                          "Vazio = todos os arquivos.")))
        self.include = QLineEdit(placeholderText="*.jpg; *.png")
        fl.addWidget(self.include)
        fl.addWidget(field_label(tr("Ignorar"), t, tr("Arquivos ou pastas a pular, separados por ponto e vírgula.\n"
                                                     "Ex.: node_modules; *.tmp; Thumbs.db; .git")))
        self.exclude = QLineEdit(placeholderText="node_modules; *.tmp; Thumbs.db")
        fl.addWidget(self.exclude)
        right.addWidget(flt_card)
        right.addStretch(1)
        cols.addLayout(right, 2)
        lay.addLayout(cols)

        # Ações ----------------------------------------------------------------------
        actions = QHBoxLayout()
        actions.setSpacing(SP_M)
        self.sim_btn = button(tr("Simular"), "secondary", t, "fa6s.eye")
        self.sim_btn.setToolTip(tr("Mostra o que seria feito, sem copiar nem apagar nada"))
        self.sim_btn.clicked.connect(lambda: self.start(dry_run=True))
        self.queue_btn = button(tr("Pôr na fila"), "secondary", t, "fa6s.list-check")
        self.queue_btn.setToolTip(tr("Guarda esta tarefa para rodar depois, em sequência com outras"))
        self.queue_btn.clicked.connect(self._enqueue)
        self.strategy = QLabel()
        self.strategy.setProperty("role", "muted")
        self.run_btn = QPushButton()
        self.run_btn.setProperty("variant", "primary")
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.setToolTip(tr("Começar agora (Ctrl+Enter)"))
        self.run_btn.clicked.connect(lambda: self.start())
        self.pause_btn = button(tr("Pausar"), "secondary", t, "fa6s.pause")
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.cancel_btn = button(tr("Cancelar"), "danger")
        self.cancel_btn.clicked.connect(self._cancel)
        actions.addWidget(self.sim_btn)
        actions.addWidget(self.queue_btn)
        actions.addWidget(self.strategy, 1)
        actions.addWidget(self.cancel_btn)
        actions.addWidget(self.pause_btn)
        actions.addWidget(self.run_btn)
        lay.addLayout(actions)

        # Andamento -------------------------------------------------------------------
        prog_card, pl = section(tr("Andamento"), "fa6s.gauge-high", t)
        self.state_lbl = QLabel(tr("Pronto"))
        self.state_lbl.setProperty("role", "muted")
        prog_card.head.addWidget(self.state_lbl)
        kpis = QHBoxLayout()
        kpis.setSpacing(SP_M)
        self.k_speed = KpiCard("fa6s.bolt", tr("Velocidade"), tr("Média dos últimos 2 segundos. Na nota, a média geral."), t)
        self.k_files = KpiCard("fa6s.file", tr("Arquivos"), tr("Copiados / total a copiar. Na nota, arquivos por segundo "
                                                   "e quantos foram pulados por já estarem iguais."), t)
        self.k_bytes = KpiCard("fa6s.database", tr("Dados"), tr("Copiado / total a copiar."), t)
        self.k_eta = KpiCard("fa6s.hourglass-half", tr("Tempo restante"), tr("Estimativa pela velocidade atual. Aparece "
                                                                    "quando a varredura das pastas termina."), t)
        for k in (self.k_speed, self.k_files, self.k_bytes, self.k_eta):
            kpis.addWidget(k, 1)
        pl.addLayout(kpis)
        self.bar = QProgressBar(textVisible=False)
        self.bar.setFixedHeight(6)
        self.bar.setRange(0, 1000)
        pl.addWidget(self.bar)
        self.current = QLabel(" ", objectName="currentFile")
        self.current.setMinimumWidth(1)
        self.current.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        pl.addWidget(self.current)
        self.chart = SpeedChart(t)
        pl.addWidget(self.chart)
        lay.addWidget(prog_card)
        lay.addStretch(1)

        ctl = self.ctl
        ctl.started.connect(self._on_started)
        ctl.tick.connect(self._on_tick)
        ctl.finished.connect(self._on_finished)
        self._restore()
        self._set_running(False)

    # Estado do formulário -------------------------------------------------------------
    def set_mode(self, m: Mode):
        self.mode = m
        self.mode_group.button(list(Mode).index(m)).setChecked(True)
        self.mode_help.setText(mode_help(m))
        delete = m == Mode.DELETE
        self.dst_card.setVisible(not delete)
        self.overwrite.setEnabled(not delete)
        self.ow_label.setEnabled(not delete)
        self.verify.setEnabled(not delete)
        self.preserve.setEnabled(not delete)
        self.extras.setEnabled(not delete)
        self.contents_only.setText(tr("Apagar só o conteúdo das pastas (mantém a pasta vazia)") if delete else
                                   tr("Copiar só o conteúdo das pastas (sem criar a pasta no destino)"))
        self.run_btn.setText(run_label(m))
        self._refresh_state()

    def _refresh_state(self):
        ok = self.sources.count() > 0 and (self.mode == Mode.DELETE or bool(self.dest.text().strip()))
        busy = self.ctl.busy
        self.run_btn.setEnabled(ok and not busy)
        self.sim_btn.setEnabled(ok and not busy)
        self.queue_btn.setEnabled(ok)

    def _add_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("Escolha uma pasta de origem"))
        if d:
            self.sources.add_paths([d])

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr("Escolha os arquivos de origem"))
        if files:
            self.sources.add_paths(files)

    def _browse_dest(self):
        d = QFileDialog.getExistingDirectory(self, tr("Escolha a pasta de destino"), self.dest.text())
        if d:
            self.dest.setText(os.path.normpath(d))

    @staticmethod
    def _patterns(text: str) -> list[str]:
        return [p.strip() for p in text.replace(",", ";").split(";") if p.strip()]

    def build_spec(self, dry_run: bool = False) -> JobSpec:
        srcs = []
        for p in self.sources.paths():
            if self.contents_only.isChecked() and os.path.isdir(p):
                p = p.rstrip("/\\") + os.sep
            srcs.append(p)
        return JobSpec(mode=self.mode, sources=srcs, dest=self.dest.text().strip(),
                       overwrite=Overwrite(self.overwrite.currentData()), verify=self.verify.isChecked(),
                       include=self._patterns(self.include.text()), exclude=self._patterns(self.exclude.text()),
                       preserve_times=self.preserve.isChecked(), extras=self.extras.isChecked(), dry_run=dry_run,
                       threads=settings.get_threads(), buffer_mb=settings.get_buffer_mb(),
                       disk_mode=settings.get_disk_mode(), unbuffered=settings.get_unbuffered(),
                       native=settings.get_native())

    def load_spec(self, spec: JobSpec):
        self.sources.clear()
        contents = any(s.endswith(("/", "\\")) for s in spec.sources)
        self.sources.add_paths([s.rstrip("/\\") if len(s) > 3 else s for s in spec.sources])
        self.contents_only.setChecked(contents)
        self.dest.setText(spec.dest)
        self.overwrite.setCurrentIndex(max(0, self.overwrite.findData(str(spec.overwrite))))
        self.verify.setChecked(spec.verify)
        self.preserve.setChecked(spec.preserve_times)
        self.extras.setChecked(spec.extras)
        self.include.setText("; ".join(spec.include))
        self.exclude.setText("; ".join(spec.exclude))
        self.set_mode(spec.mode)

    def _restore(self):
        last = settings.get_last_job()
        try:
            spec = JobSpec.from_json(last) if last else JobSpec()
        except (ValueError, TypeError, KeyError):
            spec = JobSpec()
        self.load_spec(spec)

    def _enqueue(self):
        self.enqueue.emit(self.build_spec())

    # Execução --------------------------------------------------------------------------
    def confirm(self, spec: JobSpec) -> bool:
        if spec.dry_run:
            return True
        if spec.mode == Mode.DELETE:
            n = len(spec.sources)
            return QMessageBox.question(
                self, tr("Apagar definitivamente?"),
                (tr("Apagar 1 item e tudo o que houver dentro?") if n == 1 else
                 tr("Apagar {n} itens e tudo o que houver dentro?", n=n)) + "\n\n" +
                tr("Os arquivos NÃO vão para a Lixeira. Dica: use Simular antes para ver a lista."),
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) == QMessageBox.Yes
        if spec.mode == Mode.SYNC:
            return QMessageBox.question(
                self, tr("Sincronizar?"),
                tr("O destino vai ficar igual à origem:\n{dest}\n\n"
                   "Arquivos e pastas do destino que não existem na origem serão APAGADOS.\n"
                   "Dica: use Simular antes para ver o que será apagado.", dest=spec.dest),
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) == QMessageBox.Yes
        return True

    def start(self, dry_run: bool = False, spec: JobSpec | None = None, ask: bool = True) -> bool:
        if self.ctl.busy:
            return False
        spec = spec or self.build_spec(dry_run)
        if ask and not self.confirm(spec):
            return False
        if not spec.dry_run:
            settings.set_last_job(self.build_spec().to_json())
        return self.ctl.start(spec)

    def _toggle_pause(self):
        r = self.ctl.runner
        if r is None:
            return
        if r.paused:
            self.ctl.resume()
        else:
            self.ctl.pause()

    def _cancel(self):
        if QMessageBox.question(self, tr("Cancelar?"), tr("Parar a tarefa agora? O que já foi copiado fica no "
                                                        "destino; o arquivo que estava pela metade é apagado."),
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.ctl.cancel()

    def _set_running(self, on: bool):
        self.pause_btn.setVisible(on)
        self.cancel_btn.setVisible(on)
        for w in (self.sources, self.dest, self.overwrite, self.verify, self.preserve, self.extras, self.include,
                  self.exclude, self.contents_only):
            w.setEnabled(not on)
        for b in self.mode_group.buttons():
            b.setEnabled(not on)
        self._refresh_state()

    def _on_started(self, spec: JobSpec):
        self._set_running(True)
        self.chart.clear()
        self.bar.setValue(0)
        for k in (self.k_speed, self.k_files, self.k_bytes, self.k_eta):
            k.set("—")
        self.state_lbl.setText(tr("Simulando…") if spec.dry_run else tr("Varrendo e copiando…"))
        set_tone(self.state_lbl, None)

    def _on_tick(self, s: dict):
        if s.get("paused"):
            self.state_lbl.setText(tr("Pausado"))
            self.pause_btn.setText(tr("Continuar"))
            self.pause_btn.setProperty("qtaIcon", "fa6s.play|mut|11")
        else:
            self.state_lbl.setText(tr("Varrendo e copiando…") if s["scanning"] else tr("Copiando…"))
            self.pause_btn.setText(tr("Pausar"))
            self.pause_btn.setProperty("qtaIcon", "fa6s.pause|mut|11")
        _paint(self.pause_btn, self.t)
        avg = s["done_bytes"] / s["elapsed"] if s["elapsed"] > 0 else 0
        self.k_speed.set(fmt.speed(s["speed"]), tr("média {speed}", speed=fmt.speed(avg)))
        total_files = s["scan_files"]
        self.k_files.set(f"{fmt.count(s['done_files'])} / {fmt.count(total_files)}{'+' if s['scanning'] else ''}",
                         tr("{rate} arq/s · pulados {skipped}", rate=fmt.count(s["files_per_s"]),
                            skipped=fmt.count(s["skipped_files"])))
        self.k_bytes.set(fmt.size(s["done_bytes"]),
                         tr("de {size} (varrendo)", size=fmt.size(s["scan_bytes"])) if s["scanning"]
                         else tr("de {size}", size=fmt.size(s["scan_bytes"])))
        self.k_eta.set(fmt.duration(s["eta"]), tr("decorrido {time}", time=fmt.duration(s["elapsed"])))
        if s["scan_bytes"] > 0:
            self.bar.setValue(int(1000 * s["done_bytes"] / s["scan_bytes"]))
        elif not s["scanning"]:
            self.bar.setValue(1000)
        self.current.setText(s["current"] or " ")
        if s["strategy"]:
            self.strategy.setText(s["strategy"])
        self.chart.push(s["speed"])

    def _on_finished(self, runner, s: dict, error: str):
        self._set_running(False)
        self.current.setText(" ")
        if error:
            self.state_lbl.setText(tr("Não começou"))
            set_tone(self.state_lbl, "neg")
            QMessageBox.warning(self, tr("Não foi possível começar"), error)
            return
        if runner.cancelled:
            self.state_lbl.setText(tr("Cancelado"))
            set_tone(self.state_lbl, "neg")
        elif s["errors"]:
            self.state_lbl.setText(tr("Terminou com {n} erro(s) — veja em Log", n=s["errors"]))
            set_tone(self.state_lbl, "neg")
        else:
            self.state_lbl.setText(tr("Concluído"))
            set_tone(self.state_lbl, "pos")
            self.bar.setValue(1000)
        self.k_speed.set(fmt.speed(s["avg_speed"]), tr("média geral"))
        self.k_eta.set(fmt.duration(s["elapsed"]), tr("tempo total"))
        if runner.spec.dry_run:
            PlanDialog(self, runner.plan, s).exec()

    def apply_theme(self, t: dict):
        self.t = t
        self.chart.apply_theme(t)
        self.run_btn.setIcon(qta.icon("fa6s.play", color=t["on_acc"]))
