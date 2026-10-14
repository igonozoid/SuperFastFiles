import subprocess
import sys
from pathlib import Path

import pytest

from superfastfiles import format as fmt, i18n
from superfastfiles.engine.job import Mode, mode_label

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def volta_ao_portugues():
    yield
    i18n.setup("pt_BR")


def test_catalogos_completos():
    """Todo tr("...") do código tem tradução em todos os idiomas, com os mesmos {placeholders}."""
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "i18n.py"), "--check"], capture_output=True,
                       text=True, encoding="utf-8", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 0, r.stdout


@pytest.mark.parametrize("lang,copy", [("pt_BR", "Copiar"), ("en", "Copy"), ("es", "Copiar")])
def test_troca_de_idioma(lang, copy):
    assert i18n.setup(lang) == lang
    assert mode_label(Mode.COPY) == copy
    assert i18n.tr("Mostrando os primeiros {shown} de {total}.", shown=1, total=2).count("1") == 1


def test_numeros_no_formato_do_idioma():
    i18n.setup("pt_BR")
    assert fmt.size(1536) == "1,5 KB"
    assert fmt.count(1234567) == "1.234.567"
    i18n.setup("en")
    assert fmt.size(1536) == "1.5 KB"
    assert fmt.count(1234567) == "1,234,567"


@pytest.mark.parametrize("code,expected", [("pt-PT", "pt_BR"), ("es_AR.UTF-8", "es"), ("en-GB", "en"),
                                           ("de-DE", "en"), ("", "en")])
def test_idioma_do_sistema(code, expected):
    assert i18n.match(code) == expected


@pytest.mark.parametrize("lang", list(i18n.LANGUAGES))
def test_janela_abre_em_cada_idioma(qtbot, lang):
    i18n.setup(lang)
    from superfastfiles.ui.main_window import KEYS, MainWindow
    w = MainWindow()
    qtbot.addWidget(w)
    for k in KEYS:
        w.go_to(k)
    assert w.header.title.text() == i18n.tr("Configurações")
