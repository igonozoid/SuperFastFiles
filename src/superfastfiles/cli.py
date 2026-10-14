"""Linha de comando: sff copy|move|sync|delete ORIGEM... [DESTINO]

Exemplos:
    sff copy D:\\Fotos E:\\Backup               (cria E:\\Backup\\Fotos)
    sff copy D:\\Fotos\\ E:\\Backup             (barra no fim: copia só o conteúdo)
    sff sync D:\\Projetos\\ E:\\Projetos --verify --exclude node_modules --exclude "*.tmp"
    sff delete E:\\Lixo --dry-run
Código de saída: 0 = tudo certo, 1 = terminou com erros, 2 = não começou, 3 = cancelado.
Idioma: --lang pt_BR|en|es (ou a variável SFF_LANG; sem nada, o escolhido no programa ou o do sistema).
"""
from __future__ import annotations

import argparse
import sys
import threading
import time

from superfastfiles import __version__, format as fmt
from superfastfiles import i18n
from superfastfiles.engine import JobError, JobSpec, Mode, Overwrite, Runner
from superfastfiles.engine.job import action_label
from superfastfiles.i18n import tr


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sff", description=tr("SuperFastFiles — copiador de arquivos rápido"))
    p.add_argument("--lang", choices=list(i18n.LANGUAGES), help=tr("idioma das mensagens"))
    p.add_argument("--version", action="version", version=f"SuperFastFiles {__version__}")
    sub = p.add_subparsers(dest="mode", required=True)
    for mode, help_text in (("copy", tr("copiar")), ("move", tr("mover")), ("sync", tr("sincronizar (espelhar)")),
                            ("delete", tr("apagar"))):
        sp = sub.add_parser(mode, help=help_text)
        sp.add_argument("paths", nargs="+", help=tr("origem(ns) e, por último, o destino") if mode != "delete"
                        else tr("o que apagar"))
        sp.add_argument("--include", action="append", default=[], help=tr("só arquivos que casam (glob), repetível"))
        sp.add_argument("--exclude", action="append", default=[], help=tr("ignorar arquivos/pastas (glob), repetível"))
        sp.add_argument("--min-size", type=int, default=0)
        sp.add_argument("--max-size", type=int, default=0)
        sp.add_argument("--dry-run", action="store_true", help=tr("só mostrar o que seria feito"))
        sp.add_argument("-q", "--quiet", action="store_true")
        if mode != "delete":
            sp.add_argument("--overwrite", choices=[o.value for o in Overwrite], default="diff")
            sp.add_argument("--verify", action="store_true", help=tr("conferir o destino com hash xxh3-128"))
            sp.add_argument("--threads", type=int, default=0, help=tr("0 = automático"))
            sp.add_argument("--buffer-mb", type=int, default=0, help=tr("0 = automático"))
            sp.add_argument("--disk", choices=["auto", "ssd", "hdd", "same", "net"], default="auto")
            sp.add_argument("--cached", action="store_true", help=tr("usar o cache do SO também nos arquivos grandes"))
            sp.add_argument("--no-native", action="store_true", help=tr("sempre usar o pipeline próprio"))
            sp.add_argument("--no-times", action="store_true", help=tr("não preservar datas"))
    return p


def spec_from_args(a) -> JobSpec:
    mode = Mode(a.mode)
    if mode == Mode.DELETE:
        sources, dest = a.paths, ""
    else:
        if len(a.paths) < 2:
            raise JobError(tr("Informe pelo menos uma origem e o destino."))
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
    argv = sys.argv[1:] if argv is None else list(argv)
    lang = None                                    # o idioma vale já para a ajuda (--help)
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            lang = argv[i + 1]
        elif arg.startswith("--lang="):
            lang = arg.split("=", 1)[1]
    i18n.setup(lang)
    a = build_parser().parse_args(argv)
    try:
        spec = spec_from_args(a)
        r = Runner(spec)
    except JobError as e:
        print(tr("erro: {message}", message=e), file=sys.stderr)
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
        print(tr("erro: {message}", message=result["error"]), file=sys.stderr)
        return 2
    s = r.stats.snapshot()
    for item in r.plan:
        print(f"{action_label(item.action):13} {item.path}")
    for e in r.stats.errors[:50]:
        print(tr("ERRO  {path}: {message}", path=e.path, message=e.message), file=sys.stderr)
    el = max(s["elapsed"], 1e-9)
    print(tr("{files} arquivos · {size} em {time} ({speed}) · pulados {skipped} · apagados {deleted} · "
             "erros {errors}", files=fmt.count(s["done_files"]), size=fmt.size(s["done_bytes"]),
             time=fmt.duration(el), speed=fmt.speed(s["done_bytes"] / el), skipped=fmt.count(s["skipped_files"]),
             deleted=fmt.count(s["deleted_files"]), errors=s["errors"]))
    if s["strategy"]:
        print(tr("estratégia: {name}", name=s["strategy"]))
    if r.cancelled:
        return 3
    return 1 if s["errors"] else 0


def _line(s: dict):
    el = max(s["elapsed"], 1e-9)
    total = s["scan_bytes"]
    pct = f"{100 * s['done_bytes'] / total:5.1f}%" if total and not s["scanning"] else tr(" varrendo")
    sys.stdout.write("\r" + tr("{pct}  {done}/{total} arq  {size}  {speed}   ", pct=pct,
                                done=fmt.count(s["done_files"]), total=fmt.count(s["scan_files"]),
                                size=fmt.size(s["done_bytes"]), speed=fmt.speed(s["done_bytes"] / el)))
    sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
