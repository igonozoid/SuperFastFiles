# SuperFastFiles — guia de desenvolvimento

Copiador de arquivos rápido e multiplataforma (Windows > Linux > macOS), inspirado no FastCopy. Python 3.12 + PySide6.
Interface segue os padrões do **IGNF Finora** (`../Claude_IGNF Finora_Py`): mesmo `ui/theme.py`, mesmos widgets.

## Estrutura
- `engine/` — motor **sem Qt** (usado pela CLI, pela janela e pelos testes).
  `scanner` (varredura paralela + filtros) → `runner` (decide copiar/pular, distribui em threads, pós de
  sincronizar/mover/datas) → `copier_base.Copier` (pipeline leitora+escritora, verificação) sobre uma `FileIO` por SO:
  `copier_win` (Win32 via ctypes: NO_BUFFERING, CopyFileExW), `copier_posix` (reflink, copy_file_range, clonefile,
  F_NOCACHE). `disk.py` detecta SSD/HDD/rede/mesmo disco e escolhe a `Strategy`.
- `services/` — fila e histórico (JSON em `data/`). A interface não grava arquivos direto.
- `core/` — paths (pasta `data/` portátil, `SFF_DATA_DIR`), settings (INI), logs, instância única. Copiados do Finora.
- `ui/` — `main_window` (Sidebar + Header + QStackedWidget, NAV por chave), `copy_page`, `other_pages`,
  `engine_bridge.JobController` (Runner numa thread; QTimer lê `stats.snapshot()` 10x/s).

## Regras (herdadas do Finora)
- Textos da UI em PT-BR, linguagem simples; termos técnicos ganham "?" com tooltip (`widgets.help_icon`).
- Ícones qtawesome `fa6s.`/`fa6.`. Cores só pelos tokens de `ui/theme.py` (nada de cor fixa em widget).
- Densidade: linhas 26px, fonte 9pt, espaçamentos 4/8/12. Números (MB/s, bytes, tempo) em fonte mono.
- Cartões de seção: `widgets.section(título, ícone, t)`. Botões: `widgets.button(texto, variant, t, ícone)`.
- Commits pequenos, mensagem em PT-BR.

## Regras do motor
- Nada de Qt em `engine/`. Toda chamada de E/S pesada precisa soltar o GIL (ctypes/os soltam).
- Mudou algo de desempenho? Meça com `tools/bench.py` (mediana de várias rodadas) e anote o porquê no código.
- Arquivo pela metade (erro/cancelar) é apagado. Erros por arquivo não param a tarefa: vão para `stats.error`.
- Sincronizar/Apagar sempre pedem confirmação na interface; "Simular" (dry_run) não pode alterar nada (há teste).

## Comandos
- Testes: `pytest -q` (inclui pytest-qt, offscreen). Smoke: `python -m superfastfiles --teste`.
- CLI: `sff copy ORIGEM... DESTINO [--verify] [--exclude X]` (ver `cli.py`).
- Pacote portátil: `python tools/build.py` → `dist/SuperFastFiles/` (SuperFastFiles + sff) e .zip/.tar.gz.
