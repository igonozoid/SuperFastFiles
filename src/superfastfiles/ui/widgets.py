"""Pequenos widgets reutilizáveis (mesmos do Finora)."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QLabel, QHBoxLayout, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)
import qtawesome as qta

from superfastfiles.ui import theme
from superfastfiles.ui.theme import SP_L, SP_M, SP_S


def _paint(w: QWidget, t: dict) -> None:
    name, key, px = w.property("qtaIcon").split("|")
    if isinstance(w, QAbstractButton):
        w.setIcon(qta.icon(name, color=t[key], color_active=t["fg"]))
        w.setIconSize(QSize(int(px), int(px)))
    else:
        w.setPixmap(qta.icon(name, color=t[key]).pixmap(QSize(int(px), int(px))))


def themed_icon(w: QWidget, name: str, t: dict, key: str = "mut", px: int = 12) -> QWidget:
    """Põe um ícone qtawesome num QLabel/botão e guarda a receita para `retheme`."""
    w.setProperty("qtaIcon", f"{name}|{key}|{px}")
    _paint(w, t)
    return w


def retheme(root: QWidget, t: dict) -> None:
    """Redesenha, com as cores do novo tema, todos os ícones criados por `themed_icon`."""
    for w in root.findChildren(QWidget):
        if w.property("qtaIcon"):
            _paint(w, t)


def icon_label(name: str, t: dict, key: str = "mut", px: int = 12) -> QLabel:
    return themed_icon(QLabel(), name, t, key, px)


def set_tone(w: QWidget, tone: str | None) -> None:
    """Cor semântica de um texto ('pos', 'neg', 'mut' ou None), resolvida pelo QSS do tema."""
    w.setProperty("tone", tone or "")
    w.style().unpolish(w)
    w.style().polish(w)


def help_icon(text: str, t: dict) -> QLabel:
    """Ícone "?" com explicação no tooltip, para termos técnicos."""
    lbl = icon_label("fa6.circle-question", t)
    lbl.setToolTip(text)
    lbl.setCursor(Qt.WhatsThisCursor)
    return lbl


def field_label(text: str, t: dict, help_text: str | None = None) -> QWidget:
    """Rótulo pequeno acima de um campo, com "?" opcional."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(SP_S)
    lbl = QLabel(text)
    lbl.setProperty("role", "field")
    lay.addWidget(lbl)
    w.label, w.help = lbl, None
    if help_text is not None:
        w.help = help_icon(help_text, t)
        lay.addWidget(w.help)
    lay.addStretch(1)
    return w


def button(text: str, variant: str, t: dict | None = None, icon: str | None = None, color_key: str = "mut") -> QPushButton:
    b = QPushButton(text)
    b.setProperty("variant", variant)
    b.setCursor(Qt.PointingHandCursor)
    if icon and t:
        themed_icon(b, icon, t, color_key, 11)
    return b


class WrapFrame(QFrame):
    """QFrame com texto que quebra linha (a altura necessária vira mínimo a cada largura)."""

    def resizeEvent(self, e):
        super().resizeEvent(e)
        lay = self.layout()
        if lay is not None and lay.hasHeightForWidth():
            need = lay.totalHeightForWidth(self.width())
            if need != self.minimumHeight():
                self.setMinimumHeight(need)


def section(title: str, icon: str, t: dict) -> tuple[QFrame, QVBoxLayout]:
    """Cartão com ícone âmbar e título (padrão das seções do Finora). Retorna (cartão, layout do conteúdo)."""
    box = WrapFrame(objectName="card")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(14, SP_L, 14, 14)
    lay.setSpacing(SP_M)
    head = QHBoxLayout()
    head.setSpacing(SP_M)
    head.addWidget(icon_label(icon, t, "acc", 12))
    head.addWidget(QLabel(title, objectName="sectionTitle"))
    head.addStretch(1)
    box.head = head
    lay.addLayout(head)
    return box, lay


def page_scroll(parent: QWidget) -> QVBoxLayout:
    """Corpo de página com rolagem (QScrollArea#pageScroll > QWidget#pageBody). Retorna o layout do corpo."""
    outer = QVBoxLayout(parent)
    outer.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea(objectName="pageScroll", widgetResizable=True, frameShape=QFrame.NoFrame)
    body = QWidget(objectName="pageBody")
    scroll.setWidget(body)
    outer.addWidget(scroll)
    lay = QVBoxLayout(body)
    lay.setContentsMargins(16, SP_L, 16, 16)
    lay.setSpacing(SP_L)
    return lay


class KpiCard(QFrame):
    """Cartão de indicador: ícone, rótulo, valor em fonte mono e nota (igual ao Dashboard do Finora)."""

    def __init__(self, icon: str, label: str, help_text: str, t: dict):
        super().__init__(objectName="card")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SP_L, 10, SP_L, 10)
        lay.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(icon_label(icon, t, "mut", 11))
        lbl = QLabel(label)
        lbl.setProperty("role", "muted")
        top.addWidget(lbl)
        top.addStretch(1)
        top.addWidget(help_icon(help_text, t))
        lay.addLayout(top)
        self.value = QLabel("—")
        f = theme.mono_font()
        f.setPointSize(14)
        self.value.setFont(f)
        lay.addWidget(self.value)
        self.note = QLabel(" ")
        self.note.setProperty("role", "field")
        lay.addWidget(self.note)

    def set(self, value: str, note: str = " ", tone: str | None = None):
        self.value.setText(value)
        set_tone(self.value, tone)
        self.note.setText(note)
