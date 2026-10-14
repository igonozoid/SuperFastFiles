"""Hash para verificação: xxh3-128 (dezenas de GB/s, não vira gargalo). Sem o pacote xxhash, BLAKE2b."""
from __future__ import annotations

try:
    import xxhash

    def new_hasher():
        return xxhash.xxh3_128()

    ALGORITHM = "xxh3-128"
except ImportError:          # pragma: no cover — xxhash é dependência, mas o motor funciona sem ele
    import hashlib

    def new_hasher():
        return hashlib.blake2b(digest_size=16)

    ALGORITHM = "blake2b-128"


class VerifyError(Exception):
    pass
