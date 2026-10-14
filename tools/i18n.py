"""Catálogos de tradução: extrai os textos de tr("...") do código e confere/atualiza assets/locales/*.json.

    python tools/i18n.py            # atualiza: acrescenta textos novos (vazios) e tira os que sumiram do código
    python tools/i18n.py --check    # só confere (falha se faltar tradução ou se os {placeholders} não baterem)
"""
from __future__ import annotations

import ast
import json
import re
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "superfastfiles"
sys.path.insert(0, str(ROOT / "src"))
from superfastfiles.i18n import LANGUAGES, LOCALES_DIR, SOURCE  # noqa: E402


def extract() -> dict[str, str]:
    """{texto: "arquivo:linha" da primeira ocorrência}, na ordem em que aparecem."""
    found: dict[str, str] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                    and node.args):
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.setdefault(arg.value, f"{path.relative_to(ROOT)}:{node.lineno}")
                else:
                    print(f"AVISO {path.relative_to(ROOT)}:{node.lineno}: tr() sem texto literal "
                          "(não dá para traduzir)")
    return found


def fields(s: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


def main() -> int:
    check = "--check" in sys.argv
    keys = extract()
    problems = 0
    for lang in LANGUAGES:
        if lang == SOURCE:
            continue
        path = LOCALES_DIR / f"{lang}.json"
        cat = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        missing = [k for k in keys if not cat.get(k)]
        obsolete = [k for k in cat if k not in keys]
        bad = [k for k in keys if cat.get(k) and fields(cat[k]) != fields(k)]
        for k in missing:
            print(f"[{lang}] sem tradução: {k!r}  ({keys[k]})")
        for k in bad:
            print(f"[{lang}] placeholders diferentes: {k!r} -> {cat[k]!r}")
        if obsolete:
            print(f"[{lang}] {len(obsolete)} texto(s) que não existem mais no código")
        problems += len(missing) + len(bad)
        if not check:
            new = {k: cat.get(k, "") for k in keys}
            LOCALES_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(new, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(keys)} textos no código; {problems} problema(s).")
    return 1 if (check and problems) else 0


if __name__ == "__main__":
    sys.exit(main())
