"""Liga o motor (threads Python) à interface sem travar a janela.

O Runner roda numa thread; um QTimer na thread da interface lê os contadores 10x por segundo e emite `tick`.
Nada do motor toca em widgets, e a interface não recebe uma enxurrada de sinais (um por arquivo).
"""
from __future__ import annotations

import threading
import time
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal

from superfastfiles.core.logs import log
from superfastfiles.engine import JobError, JobSpec, Runner

TICK_MS = 100
SPEED_WINDOW = 2.0            # segundos usados na média da velocidade "agora"


class JobController(QObject):
    started = Signal(object)              # JobSpec
    tick = Signal(dict)                   # snapshot + speed, files_per_s, eta
    finished = Signal(object, dict, str)  # Runner, snapshot final, mensagem de erro ("" se começou bem)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.runner: Runner | None = None
        self._thread: threading.Thread | None = None
        self._error = ""
        self._samples: deque = deque()
        self._timer = QTimer(self, interval=TICK_MS)
        self._timer.timeout.connect(self._poll)

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, spec: JobSpec) -> bool:
        if self.busy:
            return False
        self.runner = Runner(spec)
        self._error = ""
        self._samples.clear()
        log.info("Tarefa: %s %s -> %s (verificar=%s, simulação=%s)", spec.mode, spec.sources, spec.dest,
                 spec.verify, spec.dry_run)

        def work(r=self.runner):
            try:
                r.run()
            except JobError as e:
                self._error = str(e)
            except Exception as e:  # noqa: BLE001 — vai para o log e para a tela, sem derrubar o app
                log.exception("Falha na tarefa")
                self._error = f"Erro inesperado: {e}"

        self._thread = threading.Thread(target=work, name="job", daemon=True)
        self._thread.start()
        self._timer.start()
        self.started.emit(spec)
        return True

    def pause(self):
        if self.runner:
            self.runner.pause()

    def resume(self):
        if self.runner:
            self.runner.resume()

    def cancel(self):
        if self.runner:
            self.runner.cancel()

    def _poll(self):
        r = self.runner
        if r is None:
            return
        snap = r.stats.snapshot()
        now = time.monotonic()
        self._samples.append((now, snap["done_bytes"], snap["done_files"]))
        while len(self._samples) > 2 and now - self._samples[0][0] > SPEED_WINDOW:
            self._samples.popleft()
        t0, b0, f0 = self._samples[0]
        dt = now - t0
        snap["speed"] = (snap["done_bytes"] - b0) / dt if dt > 0.2 else 0.0
        snap["files_per_s"] = (snap["done_files"] - f0) / dt if dt > 0.2 else 0.0
        el = snap["elapsed"]
        avg = snap["done_bytes"] / el if el > 0 else 0
        left = snap["scan_bytes"] - snap["done_bytes"]
        rate = snap["speed"] or avg
        snap["eta"] = left / rate if (rate > 0 and not snap["scanning"]) else None
        snap["paused"] = r.paused
        alive = self._thread is not None and self._thread.is_alive()
        self.tick.emit(snap)
        if not alive:
            self._timer.stop()
            final = r.stats.snapshot()
            final["avg_speed"] = final["done_bytes"] / final["elapsed"] if final["elapsed"] > 0 else 0
            log.info("Fim: %s arquivos, %s bytes, %.1fs, %s erros%s", final["done_files"], final["done_bytes"],
                     final["elapsed"], final["errors"], " (cancelado)" if r.cancelled else "")
            self._thread = None
            self.finished.emit(r, final, self._error)
