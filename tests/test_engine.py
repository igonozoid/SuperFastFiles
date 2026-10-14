import os
import sys
import threading
import time
from pathlib import Path

import pytest

from superfastfiles.engine import JobError, JobSpec, Mode, Overwrite, Runner
from superfastfiles.engine import runner as runner_mod

WIN = sys.platform == "win32"


def make_tree(root: Path, big: int = 0) -> dict[str, bytes]:
    files = {
        "a.txt": b"ola",
        "vazio.bin": b"",
        "sub/b.jpg": os.urandom(5000),
        "sub/deep/c.tmp": b"x" * 4097,
        "sub/deep/ção ü 日本.txt": "acentos".encode(),
        "node_modules/lib.js": b"js",
    }
    if big:
        files["grande.bin"] = os.urandom(big)
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (root / "pasta_vazia").mkdir()
    return files


def run(**kw) -> Runner:
    r = Runner(JobSpec(**kw))
    r.run()
    return r


def read_tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture(params=[(True, False), (False, False), (True, True), (False, True)],
                ids=["nativo", "pipeline", "nativo-sem-cache-verif", "pipeline-verif"])
def variant(request):
    return request.param


def test_copia_arvore_inteira(tmp_path, variant):
    native, verify = variant
    src = tmp_path / "src"
    files = make_tree(src, big=9 << 20 | 123)            # passa do limite de "grande" e não é múltiplo do setor
    r = run(mode=Mode.COPY, sources=[str(src)], dest=str(tmp_path / "dst"), native=native, verify=verify,
            unbuffered=True)
    assert r.stats.errors == []
    assert read_tree(tmp_path / "dst" / "src") == files
    assert (tmp_path / "dst" / "src" / "pasta_vazia").is_dir()
    s = r.stats.snapshot()
    assert s["done_files"] == len(files)
    assert s["done_bytes"] == sum(map(len, files.values()))


def test_preserva_data_de_modificacao(tmp_path):
    src = tmp_path / "src"
    make_tree(src)
    old = time.time() - 86400 * 30
    os.utime(src / "a.txt", (old, old))
    for native in (True, False):
        dst = tmp_path / f"dst{native}"
        run(mode=Mode.COPY, sources=[str(src) + os.sep], dest=str(dst), native=native)
        assert abs((dst / "a.txt").stat().st_mtime - old) < 2


def test_barra_no_fim_copia_so_o_conteudo(tmp_path):
    src = tmp_path / "src"
    make_tree(src)
    run(mode=Mode.COPY, sources=[str(src) + os.sep], dest=str(tmp_path / "dst"))
    assert (tmp_path / "dst" / "a.txt").exists()
    assert not (tmp_path / "dst" / "src").exists()


def test_segunda_vez_pula_os_iguais(tmp_path):
    src = tmp_path / "src"
    files = make_tree(src)
    run(mode=Mode.COPY, sources=[str(src)], dest=str(tmp_path / "dst"))
    r = run(mode=Mode.COPY, sources=[str(src)], dest=str(tmp_path / "dst"))
    s = r.stats.snapshot()
    assert s["done_files"] == 0
    assert s["skipped_files"] == len(files)


def test_sobrescreve_quando_muda(tmp_path):
    src = tmp_path / "src"
    make_tree(src)
    run(mode=Mode.COPY, sources=[str(src)], dest=str(tmp_path / "dst"))
    (src / "a.txt").write_bytes(b"mudou bastante")
    r = run(mode=Mode.COPY, sources=[str(src)], dest=str(tmp_path / "dst"))
    assert r.stats.snapshot()["done_files"] == 1
    assert (tmp_path / "dst" / "src" / "a.txt").read_bytes() == b"mudou bastante"


def test_nunca_sobrescrever(tmp_path):
    src = tmp_path / "src"
    make_tree(src)
    dst = tmp_path / "dst" / "src"
    dst.mkdir(parents=True)
    (dst / "a.txt").write_bytes(b"meu")
    run(mode=Mode.COPY, sources=[str(src)], dest=str(tmp_path / "dst"), overwrite=Overwrite.NEVER)
    assert (dst / "a.txt").read_bytes() == b"meu"


def test_sobrescreve_somente_leitura(tmp_path):
    src = tmp_path / "src"
    make_tree(src)
    dst = tmp_path / "dst" / "src"
    dst.mkdir(parents=True)
    (dst / "a.txt").write_bytes(b"antigo")
    os.chmod(dst / "a.txt", 0o444)
    r = run(mode=Mode.COPY, sources=[str(src)], dest=str(tmp_path / "dst"), overwrite=Overwrite.ALWAYS)
    assert r.stats.errors == []
    assert (dst / "a.txt").read_bytes() == b"ola"


def test_filtros(tmp_path):
    src = tmp_path / "src"
    make_tree(src)
    run(mode=Mode.COPY, sources=[str(src) + os.sep], dest=str(tmp_path / "dst"),
        exclude=["node_modules", "*.tmp"])
    got = read_tree(tmp_path / "dst")
    assert "node_modules/lib.js" not in got
    assert "sub/deep/c.tmp" not in got
    assert "a.txt" in got
    run(mode=Mode.COPY, sources=[str(src) + os.sep], dest=str(tmp_path / "dst2"), include=["*.jpg"])
    assert set(read_tree(tmp_path / "dst2")) == {"sub/b.jpg"}


def test_sincronizar_apaga_o_que_sumiu(tmp_path):
    src = tmp_path / "src"
    make_tree(src)
    dst = tmp_path / "dst"
    run(mode=Mode.SYNC, sources=[str(src) + os.sep], dest=str(dst))
    (dst / "sobra.txt").write_bytes(b"x")
    (dst / "sub" / "pasta_sobra").mkdir()
    (dst / "sub" / "pasta_sobra" / "f").write_bytes(b"y")
    (dst / "manter.log").write_bytes(b"z")
    r = run(mode=Mode.SYNC, sources=[str(src) + os.sep], dest=str(dst), exclude=["*.log"])
    assert not (dst / "sobra.txt").exists()
    assert not (dst / "sub" / "pasta_sobra").exists()
    assert (dst / "manter.log").exists()          # filtrado: não mexe
    assert r.stats.snapshot()["deleted_files"] == 2


def test_simulacao_nao_altera_nada(tmp_path):
    src = tmp_path / "src"
    files = make_tree(src)
    r = run(mode=Mode.COPY, sources=[str(src)], dest=str(tmp_path / "dst"), dry_run=True)
    assert not (tmp_path / "dst").exists()
    assert len([p for p in r.plan if p.action == "copy"]) == len(files)


def test_mover_mesmo_volume_renomeia(tmp_path):
    src = tmp_path / "src"
    files = make_tree(src)
    run(mode=Mode.MOVE, sources=[str(src)], dest=str(tmp_path / "dst"))
    assert not src.exists()
    assert read_tree(tmp_path / "dst" / "src") == files


def test_mover_com_copia(tmp_path, monkeypatch):
    src = tmp_path / "src"
    files = make_tree(src)
    monkeypatch.setattr(runner_mod.metadata, "same_volume", lambda a, b: False)   # simula outro disco
    r = run(mode=Mode.MOVE, sources=[str(src)], dest=str(tmp_path / "dst"), verify=True)
    assert r.stats.errors == []
    assert not src.exists()
    assert read_tree(tmp_path / "dst" / "src") == files


def test_apagar(tmp_path):
    src = tmp_path / "src"
    files = make_tree(src)
    r = run(mode=Mode.DELETE, sources=[str(src)])
    assert not src.exists()
    assert r.stats.snapshot()["deleted_files"] == len(files)


def test_destino_dentro_da_origem(tmp_path):
    src = tmp_path / "src"
    make_tree(src)
    with pytest.raises(JobError):
        run(mode=Mode.COPY, sources=[str(src)], dest=str(src / "dentro"))


def test_caminho_longo(tmp_path):
    src = tmp_path / "src"
    deep = src
    for i in range(12):
        deep = deep / ("pasta_com_nome_comprido_" + str(i))
    os.makedirs("\\\\?\\" + str(deep) if WIN else deep)
    target = ("\\\\?\\" + str(deep / "arquivo.txt")) if WIN else deep / "arquivo.txt"
    with open(target, "wb") as f:
        f.write(b"longe")
    r = run(mode=Mode.COPY, sources=[str(src)], dest=str(tmp_path / "dst"))
    assert r.stats.errors == []
    assert r.stats.snapshot()["done_files"] == 1


@pytest.mark.parametrize("size", [0, 1, 4095, 4096, 4097, (1 << 20) + 1, (9 << 20) + 7])
def test_pipeline_sem_cache_tamanhos_quebrados(tmp_path, size):
    from superfastfiles.engine.copier_base import Copier, CopyContext
    data = os.urandom(size)
    (tmp_path / "a").write_bytes(data)
    c = Copier(runner_mod.get_io(), 1 << 20, 3)
    ev, run_ev = threading.Event(), threading.Event()
    run_ev.set()
    got = []
    ctx = CopyContext(got.append, ev, run_ev, verify=True, unbuffered=True, native=False, unbuffered_min=0)
    c.copy(str(tmp_path / "a"), str(tmp_path / "b"), size, 0, 0, 0o644, ctx)
    assert (tmp_path / "b").read_bytes() == data
    assert sum(got) == size


def test_cancelar(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(300):
        (src / f"f{i}.bin").write_bytes(os.urandom(20000))
    r = Runner(JobSpec(mode=Mode.COPY, sources=[str(src)], dest=str(tmp_path / "dst"), threads=1))
    r.pause()
    t = threading.Thread(target=r.run)
    t.start()
    time.sleep(0.3)
    r.cancel()
    t.join(10)
    assert not t.is_alive()
    assert r.stats.snapshot()["done_files"] < 300
