"""Tabela simples no padrão do Finora: sem grade, linhas de 26px, seleção por linha, números em fonte mono."""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

from superfastfiles.ui import theme


class RowsModel(QAbstractTableModel):
    def __init__(self, headers: list[str], mono: set[int] = frozenset(), right: set[int] = frozenset()):
        super().__init__()
        self.headers = headers
        self.rows: list[list] = []
        self.payload: list = []
        self.mono, self.right = mono, right
        self.tones: list[str | None] = []
        self._font = theme.mono_font()

    def set_rows(self, rows: list[list], payload: list | None = None, tones: list | None = None):
        self.beginResetModel()
        self.rows = rows
        self.payload = payload or [None] * len(rows)
        self.tones = tones or [None] * len(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.headers[section]
        if orientation == Qt.Horizontal and role == Qt.TextAlignmentRole and section in self.right:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return str(self.rows[r][c])
        if role == Qt.FontRole and c in self.mono:
            return self._font
        if role == Qt.TextAlignmentRole:
            return int((Qt.AlignRight if c in self.right else Qt.AlignLeft) | Qt.AlignVCenter)
        if role == Qt.ForegroundRole and self.tones[r] and c == 0:
            from PySide6.QtGui import QColor
            t = theme.tokens(getattr(self, "theme_name", "light"))
            return QColor(t.get(self.tones[r], t["fg"]))
        return None


def make_table(model: RowsModel, stretch: int = 1, widths: dict[int, int] | None = None) -> QTableView:
    v = QTableView()
    v.setModel(model)
    v.setShowGrid(False)
    v.setSelectionBehavior(QAbstractItemView.SelectRows)
    v.setEditTriggers(QAbstractItemView.NoEditTriggers)
    v.verticalHeader().setVisible(False)
    v.verticalHeader().setDefaultSectionSize(theme.ROW_H)
    v.horizontalHeader().setHighlightSections(False)
    v.setWordWrap(False)
    v.setTextElideMode(Qt.ElideMiddle)
    h = v.horizontalHeader()
    h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    for col, w in (widths or {}).items():
        h.setSectionResizeMode(col, QHeaderView.Interactive)
        v.setColumnWidth(col, w)
    h.setSectionResizeMode(stretch, QHeaderView.Stretch)
    return v
