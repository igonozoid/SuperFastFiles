"""Linha de comando: sff copy|move|sync|delete ORIGEM... [DESTINO]

Exemplos:
    sff copy D:\\Fotos E:\\Backup               (cria E:\\Backup\\Fotos)
    sff copy D:\\Fotos\\ E:\\Backup             (barra no fim: copia só o conteúdo)
    sff sync D:\\Projetos\\ E:\\Projetos --verify --exclude node_modules --exclude "*.tmp"
    sff delete E:\\Lixo --dry-run
Código de saída: 0 = tudo certo, 1 = terminou com erros, 2 = não começou, 3 = cancelado.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time

from superfastfiles import __version__, format as fmt
from superfastfiles.engine import JobError, JobSpec, Mode, Overwrite, Runner


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sff", description="SuperFastFiles — copiador de arquivos rápido")
    p.add_argument("--version", action="version", version=f"SuperFastFiles {__version__}")
    sub = p.add_subparsers(dest="mode", required=True)
    for mode, help_text in (("copy", "copiar"), ("move", "mover"), ("sync", "sincronizar (espelhar)"),
                            ("delete", "apagar")):
        sp = sub.add_parser(mode, help=help_text)
        sp.add_argument("paths", nargs="+", help="origem(ns) e, por último, o destino" if mode != "delete"
                        else "o que apagar")
        sp.add_argument("--include", action="append", default=[], help="só arquivos que casam (glob), repetível")
        sp.add_argument("--exclude", action="append", default=[], help="ignorar arquivos/pastas (glob), repetível")
        sp.add_argument("--min-size", type=int, default=0)
        sp.add_argument("--max-size", type=int, default=0)
        sp.add_argument("--dry-run", action="store_true", help="só mostrar o que seria feito")
        sp.add_argument("-q", "--quiet", action="store_true")
        if mode != "delete":
            sp.add_argument("--overwrite", choices=[o.value for o in Overwrite], default="diff")
            sp.add_argument("--verify", action="store_true", help="conferir o destino com hash xxh3-128")
            sp.add_argument("--threads", type=int, default=0, help="0 = automático")
            sp.add_argument("--buffer-mb", type=int, default=0, help="0 = automático")
            sp.add_argument("--disk", choices=["auto", "ssd", "hdd", "same", "net"], default="auto")
            sp.add_argument("--cached", action="store_true", help="usar o cache do SO também nos arquivos grandes")
            sp.add_argument("--no-native", action="store_true", help="sempre usar o pipeline próprio")
            sp.add_argument("--no-times", action="store_true", help="não preservar datas")
    return p


def spec_from_args(a) -> JobSpec:
    mode = Mode(a.mode)
    if mode == Mode.DELETE:
        sources, dest = a.paths, ""
    else:
        if len(a.paths) < 2:
            raise JobError("Informe pelo menos uma origem e o destino.")
        sources, dest = a.paths[:-1], a.paths[-1]
    spec = JobSpec(mode=mode, sources=sources, dest=dest, include=a.include, exclude=a.exclude,
                   min_size=a.min_size, max_size=a.max_size, dry_run=a.dry_run)
    if mode != Mode.DELETE:
        spec.overwrite = Overwrite(a.overwrite)
        spec.verify = a.verify
        spec.threads = a.threads
        spec.buffer_mb = a.buffer_mb
        spec.disk_mode = a.disk
        spec.unbuffered = not a.cached
        spec.native = not a.no_native
        spec.preserve_times = not a.no_times
    return spec


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    try:
        spec = spec_from_args(a)
        r = Runner(spec)
    except JobError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    result: dict = {}

    def work():
        try:
            r.run()
        except JobError as e:
            result["error"] = str(e)

    t = threading.Thread(target=work, daemon=True)
    t.start()
    try:
        while t.is_alive():
            t.join(0.5)
            if not a.quiet:
                _line(r.stats.snapshot())
    except KeyboardInterrupt:
        r.cancel()
        t.join()
    if not a.quiet:
        sys.stdout.write("\n")
    if "error" in result:
        print(f"erro: {result['error']}", file=sys.stderr)
        return 2
    s = r.stats.snapshot()
    for item in r.plan:
        print(f"{item.action:13} {item.path}")
    for e in r.stats.errors[:50]:
        print(f"ERRO {e.path}: {e.message}", file=sys.stderr)
    el = max(s["elapsed"], 1e-9)
    print(f"{fmt.count(s['done_files'])} arquivos · {fmt.size(s['done_bytes'])} em {fmt.duration(el)} "
          f"({fmt.speed(s['done_bytes'] / el)}) · pulados {fmt.count(s['skipped_files'])} · "
          f"apagados {fmt.count(s['deleted_files'])} · erros {s['errors']}")
    if s["strategy"]:
        print(f"estratégia: {s['strategy']}")
    if r.cancelled:
        return 3
    return 1 if s["errors"] else 0


def _line(s: dict):
    el = max(s["elapsed"], 1e-9)
    total = s["scan_bytes"]
    pct = f"{100 * s['done_bytes'] / total:5.1f}%" if total and not s["scanning"] else " varrendo"
    sys.stdout.write(f"\r{pct}  {fmt.count(s['done_files'])}/{fmt.count(s['scan_files'])} arq  "
                     f"{fmt.size(s['done_bytes'])}  {fmt.speed(s['done_bytes'] / el)}   ")
    sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
