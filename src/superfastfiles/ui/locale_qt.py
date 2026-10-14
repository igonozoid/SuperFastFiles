"""Idioma nas partes que o próprio Qt desenha: botões padrão ("Sim"/"Yes", "Cancelar"/"Cancel"), menus de
contexto de campos de texto, diálogos de arquivo. Usa as traduções que vêm com o PySide6 (qtbase_<idioma>.qm)."""
from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

QT_LOCALES = {"pt_BR": (QLocale.Portuguese, QLocale.Brazil), "en": (QLocale.English, QLocale.UnitedStates),
              "es": (QLocale.Spanish, QLocale.Spain)}


def install(app, lang: str) -> bool:
    """True se a tradução do Qt foi carregada (inglês não precisa: é o idioma original do Qt)."""
    language, country = QT_LOCALES.get(lang, QT_LOCALES["en"])
    loc = QLocale(language, country)
    QLocale.setDefault(loc)
    if lang == "en":
        return True
    tr = QTranslator(app)
    ok = tr.load(loc, "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath))
    if ok:
        app.installTranslator(tr)
        app._qt_translator = tr    # mantém a referência viva enquanto o app existir
    return ok
