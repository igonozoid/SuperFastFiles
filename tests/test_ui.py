import os

from superfastfiles.engine import Mode
from superfastfiles.services import jobs
from superfastfiles.ui.main_window import KEYS, MainWindow


def test_janela_copia_pela_tela(qtbot, tmp_path):
    src = tmp_path / "origem"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "a.txt").write_bytes(b"abc")
    w = MainWindow()
    qtbot.addWidget(w)
    for k in KEYS:
        w.go_to(k)
    page = w.page("copy")
    page.sources.clear()
    page.sources.add_paths([str(src)])
    page.dest.setText(str(tmp_path / "destino"))
    page.set_mode(Mode.COPY)
    assert page.run_btn.isEnabled()
    with qtbot.waitSignal(w.ctl.finished, timeout=20000):
        assert page.start(ask=False)
    assert (tmp_path / "destino" / "origem" / "sub" / "a.txt").read_bytes() == b"abc"
    assert jobs.history()[0].files == 1
    assert "Concluído" in page.state_lbl.text()


def test_fila_roda_em_sequencia(qtbot, tmp_path):
    w = MainWindow()
    qtbot.addWidget(w)
    jobs.set_queue([])
    page = w.page("copy")
    for i in range(2):
        s = tmp_path / f"o{i}"
        s.mkdir()
        (s / "f.bin").write_bytes(os.urandom(1000))
        page.sources.clear()
        page.sources.add_paths([str(s)])
        page.dest.setText(str(tmp_path / "d"))
        page._enqueue()
    assert len(jobs.queue()) == 2
    w.run_queue()
    qtbot.waitUntil(lambda: not w.running_queue and not w.ctl.busy, timeout=20000)
    assert (tmp_path / "d" / "o0" / "f.bin").exists() and (tmp_path / "d" / "o1" / "f.bin").exists()
    assert jobs.queue() == []


def test_alternar_tema(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    before = w.theme_name
    w.toggle_theme()
    assert w.theme_name != before
