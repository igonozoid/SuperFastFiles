"""Formatação de números para o usuário (bytes, velocidade, tempo), nos separadores do idioma ativo."""
from superfastfiles.i18n import number


def size(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{number(n, 0 if unit == 'B' else 1)} {unit}"
        n /= 1024
    return f"{number(n, 1)} PB"


def speed(bytes_per_s: float) -> str:
    return size(bytes_per_s) + "/s"


def duration(s: float | None) -> str:
    if s is None or s != s or s < 0:
        return "—"
    s = int(round(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def count(n: float) -> str:
    return number(n, 0)
