"""Idiomas. O texto-fonte do código é o português do Brasil; as traduções ficam em assets/locales/<código>.json
({"texto em português": "tradução"}).

    from superfastfiles.i18n import tr
    tr("Copiar")                              -> "Copy" (com o idioma em inglês)
    tr("{n} arquivos copiados", n=3)          -> placeholders nomeados, como str.format

Regras:
- Sempre `tr("texto literal")` (o extrator `tools/i18n.py` procura chamadas com texto literal).
  Nada de tr(variável) nem tr(f"...").
- Constantes de módulo com texto traduzível viram funções (o idioma é escolhido depois do import).
- Sem Qt aqui: o motor e a linha de comando também usam.

Para criar um idioma: copie assets/locales/en.json para <código>.json, traduza os valores, acrescente em LANGUAGES
e rode `python tools/i18n.py --check`.
"""
from __future__ import annotations

import configparser
import json
import os
import sys
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent / "assets" / "locales"
SOURCE = "pt_BR"
# código -> nome no próprio idioma (aparece assim no seletor)
LANGUAGES = {"pt_BR": "Português (Brasil)", "en": "English", "es": "Español"}

_lang = SOURCE
_catalog: dict[str, str] = {}


def tr(text: str, **kw) -> str:
    s = _catalog.get(text) or text
    return s.format(**kw) if kw else s


def current() -> str:
    return _lang


def system_language() -> str:
    """Idioma do sistema, entre os que existem (sem ele, inglês)."""
    code = ""
    if sys.platform == "win32":
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            buf = ctypes.create_unicode_buffer(85)
            # idioma da interface do Windows (não o formato regional)
            if k32.LCIDToLocaleName(k32.GetUserDefaultUILanguage(), buf, 85, 0):
                code = buf.value                                   # "pt-BR", "en-US"
        except (OSError, AttributeError):
            code = ""
    if not code:
        for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
            if os.environ.get(var):
                code = os.environ[var]
                break
    return match(code)


def match(code: str) -> str:
    code = (code or "").replace("-", "_").split(".")[0]
    if code in LANGUAGES:
        return code
    base = code.split("_")[0].lower()
    if base == "pt":
        return "pt_BR"
    return base if base in LANGUAGES else "en"


def saved_language() -> str:
    """Escolha salva em Configurações (lê o INI sem Qt, para a linha de comando também respeitar)."""
    env = os.environ.get("SFF_LANG")
    if env:
        return env
    try:
        from superfastfiles.core.paths import DATA_DIR
        cp = configparser.RawConfigParser()
        cp.read(DATA_DIR / "superfastfiles.ini", encoding="utf-8")
        return cp.get("ui", "language", fallback="auto")
    except (configparser.Error, OSError):
        return "auto"


def setup(lang: str | None = None) -> str:
    """Ativa um idioma ("auto" = o do sistema). Retorna o código usado."""
    global _lang, _catalog
    lang = lang or saved_language()
    lang = system_language() if lang in ("", "auto") else match(lang)
    _lang = lang
    _catalog = {}
    if lang != SOURCE:
        try:
            _catalog = json.loads((LOCALES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _catalog = {}
    return lang


# Números: separadores de milhar e decimal de cada idioma
_SEPARATORS = {"pt_BR": (".", ","), "es": (".", ","), "en": (",", ".")}


def number(value: float, decimals: int = 0) -> str:
    thousands, dec = _SEPARATORS.get(_lang, (",", "."))
    s = f"{value:,.{decimals}f}"
    return s.replace(",", "\0").replace(".", dec).replace("\0", thousands)
