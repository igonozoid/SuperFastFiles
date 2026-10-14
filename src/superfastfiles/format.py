"""Formatação de números para o usuário (bytes, velocidade, tempo), em pt-BR."""


def size(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}".replace(",", "X").replace(".", ",").replace("X", ".")
        n /= 1024
    return f"{n:.1f} PB"


def speed(bytes_per_s: float) -> str:
    return size(bytes_per_s) + "/s"


def duration(s: float | None) -> str:
    if s is None or s != s or s < 0:
        return "—"
    s = int(round(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def count(n: int) -> str:
    return f"{n:,}".replace(",", ".")
