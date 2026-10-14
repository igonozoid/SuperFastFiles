"""Benchmark: SuperFastFiles x robocopy x FastCopy (se informado) x cópia simples do Python.

    python tools/bench.py --work E:\\bench --dest K:\\bench [--fastcopy "C:\\FastCopy\\fcp.exe"] [--sets big,small,mixed]

- `--work`: onde os conjuntos de teste são criados (origem). `--dest`: onde as cópias são gravadas.
  Para medir de verdade, use discos diferentes e arquivos maiores que a RAM livre (ou reinicie entre rodadas):
  depois de criados, os arquivos de origem ficam no cache do sistema e a leitura parece mais rápida que o disco.
- Cada ferramenta roda `--runs` vezes (alternando), o destino é apagado antes de cada rodada; mostra a mediana.
"""
from __future__ import annotations

import argparse
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from superfastfiles import format as fmt  # noqa: E402
from superfastfiles.engine import JobSpec, Mode, Runner  # noqa: E402

SETS = {
    "big": [("grande.bin", 4 << 30)],                                   # 1 arquivo de 4 GB
    "small": [(f"d{i // 1000}/f{i}.dat", 8 << 10) for i in range(20000)],  # 20 mil de 8 KB
    "mixed": ([(f"m/d{i // 200}/f{i}.dat", (i * 7919) % (2 << 20) + 1) for i in range(3000)]
              + [(f"m/v{i}.bin", 256 << 20) for i in range(4)]),
}


def make_set(base: Path, name: str) -> tuple[Path, int, int]:
    root = base / name
    marker = root / ".ok"
    files = SETS[name]
    total = sum(s for _f, s in files)
    if marker.exists():
        return root, len(files), total
    chunk = os.urandom(16 << 20)
    for rel, size in files:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            left = size
            while left:
                n = min(left, len(chunk))
                f.write(chunk[:n])
                left -= n
    marker.write_text("ok")
    return root, len(files), total


def rm(p: Path):
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)


def t_sff(native: bool):
    def run(src: Path, dst: Path):
        r = Runner(JobSpec(mode=Mode.COPY, sources=[str(src) + os.sep], dest=str(dst), native=native))
        r.run()
        assert not r.stats.errors, r.stats.errors[:3]
        return r.stats.strategy
    return run


def t_robocopy(src: Path, dst: Path):
    subprocess.run(["robocopy", str(src), str(dst), "/E", "/MT:32", "/NJH", "/NJS", "/NFL", "/NDL", "/NP", "/R:0",
                    "/W:0", "/XF", ".ok"], stdout=subprocess.DEVNULL)


def t_fastcopy(exe: str):
    def run(src: Path, dst: Path):
        dst.mkdir(parents=True, exist_ok=True)
        subprocess.run([exe, "/cmd=diff", "/auto_close", "/no_ui", str(src) + "\\", f"/to={dst}\\"],
                       stdout=subprocess.DEVNULL)
    return run


def t_shutil(src: Path, dst: Path):
    shutil.copytree(src, dst, dirs_exist_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--dest", required=True)
    ap.add_argument("--sets", default="small,mixed,big")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--fastcopy", default="")
    ap.add_argument("--skip", default="", help="ferramentas a pular, separadas por vírgula")
    a = ap.parse_args()
    tools = {"sff (nativo)": t_sff(True), "sff (pipeline)": t_sff(False), "shutil": t_shutil}
    if sys.platform == "win32":
        tools["robocopy /MT:32"] = t_robocopy
    if a.fastcopy:
        tools["FastCopy"] = t_fastcopy(a.fastcopy)
    for s in a.skip.split(","):
        tools.pop(s.strip(), None)
    work, dest = Path(a.work), Path(a.dest)
    print(f"origem {work} -> destino {dest}")
    for name in a.sets.split(","):
        src, n, total = make_set(work, name)
        print(f"\n== {name}: {fmt.count(n)} arquivos, {fmt.size(total)}")
        times: dict[str, list[float]] = {k: [] for k in tools}
        for _ in range(a.runs):
            for label, fn in tools.items():
                dst = dest / f"{name}-{label.split()[0]}"
                rm(dst)
                t0 = time.perf_counter()
                info = fn(src, dst)
                times[label].append(time.perf_counter() - t0)
                if info and _ == 0:
                    print(f"   ({label}: {info})")
                rm(dst)
        for label, ts in sorted(times.items(), key=lambda kv: statistics.median(kv[1])):
            m = statistics.median(ts)
            print(f"  {label:18} {m:8.2f} s   {fmt.speed(total / m):>12}   {n / m:10,.0f} arq/s")


if __name__ == "__main__":
    main()
