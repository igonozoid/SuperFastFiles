"""Gráfico de velocidade (últimos ~60 s), desenhado à mão: leve e com as cores do tema."""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from superfastfiles import format as fmt

POINTS = 600          # 60 s com um ponto a cada 100 ms


class SpeedChart(QWidget):
    def __init__(self, t: dict, parent=None):
        super().__init__(parent)
        self.t = t
        self.values: deque[float] = deque(maxlen=POINTS)
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(90)

    def apply_theme(self, t: dict):
        self.t = t
        self.update()

    def clear(self):
        self.values.clear()
        self.update()

    def push(self, v: float):
        self.values.append(v)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        t = self.t
        p.setPen(QPen(QColor(t["line"]), 1))
        for i in range(1, 4):
            y = round(h * i / 4) + 0.5
            p.drawLine(QPointF(0, y), QPointF(w, y))
        if len(self.values) < 2:
            return
        top = max(self.values) * 1.15 or 1
        step = w / (POINTS - 1)
        x0 = w - (len(self.values) - 1) * step
        path = QPainterPath()
        path.moveTo(x0, h)
        for i, v in enumerate(self.values):
            path.lineTo(x0 + i * step, h - (v / top) * (h - 14))
        path.lineTo(w, h)
        fill = QColor(t["acc"])
        fill.setAlpha(40)
        p.fillPath(path, fill)
        line = QPainterPath()
        for i, v in enumerate(self.values):
            pt = QPointF(x0 + i * step, h - (v / top) * (h - 14))
            line.moveTo(pt) if i == 0 else line.lineTo(pt)
        p.setPen(QPen(QColor(t["acc"]), 1.5))
        p.drawPath(line)
        p.setPen(QColor(t["mut"]))
        f = p.font()
        f.setPointSize(8)
        p.setFont(f)
        p.drawText(4, 12, f"pico {fmt.speed(max(self.values))}")
        p.drawText(self.rect().adjusted(0, 0, -4, 0), Qt.AlignRight | Qt.AlignTop, "últimos 60 s")
