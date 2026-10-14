"""Preferências num arquivo INI portátil (data/superfastfiles.ini), um getter/setter por chave."""
from PySide6.QtCore import QSettings

from superfastfiles.core.paths import DATA_DIR

ORG = "IGNF"
APP = "SuperFastFiles"
FILE = DATA_DIR / "superfastfiles.ini"

NAV_MODES = {"sidebar": "barra lateral", "rail": "só ícones"}


def _s() -> QSettings:
    return QSettings(str(FILE), QSettings.IniFormat)


def _get(key: str, default, kind=str):
    v = _s().value(key, default)
    if kind is bool:
        return v in (True, "true", "1", 1)
    try:
        return kind(v)
    except (TypeError, ValueError):
        return default


def _set(key: str, value) -> None:
    s = _s()
    s.setValue(key, value)
    s.sync()


# Interface
def get_theme(default="light") -> str: return _get("ui/theme", default)
def set_theme(name: str): _set("ui/theme", name)
def get_nav(default="sidebar") -> str: return _get("ui/nav", default)
def set_nav(mode: str): _set("ui/nav", mode)
def get_geometry(): return _s().value("ui/geometry")
def set_geometry(g): _set("ui/geometry", g)
def get_tray() -> bool: return _get("ui/tray", True, bool)
def set_tray(on: bool): _set("ui/tray", on)

# Motor (0 = automático)
def get_threads() -> int: return _get("engine/threads", 0, int)
def set_threads(n: int): _set("engine/threads", int(n))
def get_buffer_mb() -> int: return _get("engine/buffer_mb", 0, int)
def set_buffer_mb(n: int): _set("engine/buffer_mb", int(n))
def get_disk_mode() -> str: return _get("engine/disk_mode", "auto")
def set_disk_mode(m: str): _set("engine/disk_mode", m)
def get_unbuffered() -> bool: return _get("engine/unbuffered", True, bool)
def set_unbuffered(on: bool): _set("engine/unbuffered", on)
def get_native() -> bool: return _get("engine/native", True, bool)
def set_native(on: bool): _set("engine/native", on)

# Última tarefa (para reabrir como estava)
def get_last_job() -> str: return _get("job/last", "")
def set_last_job(js: str): _set("job/last", js)
