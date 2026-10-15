# SuperFastFiles

Copiador de arquivos rápido para Windows, Linux e macOS, inspirado no [FastCopy](https://fastcopy.jp).
Copiar, Mover, Sincronizar (espelhar) e Apagar, com filtros, verificação por hash (xxh3-128), simulação,
fila de tarefas, histórico e linha de comando. Interface no padrão visual do IGNF Finora (tema claro/escuro),
em português, inglês e espanhol (Configurações › Idioma; na linha de comando, `--lang`).

Desenvolvido por IGNF Projetos e Serviços de Engenharia LTDA — https://ignf.com.br

## Por que é rápido
- **Estratégia por disco**: detecta SSD, HDD, rede e se origem e destino são o mesmo disco físico.
  Mesmo HDD → sequencial com blocos grandes; SSD → muitas threads; rede → muitas threads + cópia no servidor.
- **Arquivos grandes**: pipeline com uma thread lendo e outra gravando ao mesmo tempo, buffers alinhados
  reaproveitados, E/S **sem cache do sistema** (como o FastCopy) e pré-alocação do destino.
- **Arquivos pequenos**: até 64 threads usando a cópia do próprio SO (CopyFileEx no Windows).
- **Cópia instantânea quando dá**: reflink (Btrfs/XFS), clonefile (APFS), copy_file_range (Linux/NFS/SMB).
- **Varredura paralela** que já vai alimentando a cópia, e leitura do destino uma vez por pasta (não um stat por arquivo).
- Verificação calcula o hash da origem no mesmo buffer da cópia (não lê duas vezes) e relê o destino sem cache.

Medições (Windows 11, `tools/bench.py`, mediana de 2–3 rodadas; FastCopy 5.11.3 com `/no_ui`, sem verificação):

**NVMe → HD externo USB (Samsung M3 Portable)**

| Conjunto | SuperFastFiles | FastCopy | robocopy /MT:32 |
|---|---|---|---|
| 20.000 arquivos de 8 KB | 318 arq/s | 313 arq/s | 325 arq/s (empate: limite do HD) |
| 3.000 arquivos mistos + 4×256 MB (3,9 GB) | **39,3 MB/s** | 29,0 MB/s | 18,4 MB/s |
| 1 arquivo de 4 GB | 58,9 MB/s | 39,9 MB/s | 68,6 MB/s ¹ |

¹ O robocopy grava pelo cache do Windows e termina antes de tudo chegar ao disco; o SuperFastFiles e o FastCopy
gravam direto no disco (sem cache) e só terminam com o arquivo gravado.

**Mesmo NVMe (origem e destino no mesmo disco)**

| Conjunto | SuperFastFiles | robocopy /MT:32 |
|---|---|---|
| 20.000 arquivos de 8 KB | **4.305 arq/s** | 2.809 arq/s |
| 3.000 arquivos mistos + 4×256 MB (3,9 GB) | 113 MB/s | 117 MB/s (empate: limite do disco) |

Comparar na sua máquina: `python tools/bench.py --work C:\bench --dest K:\bench --fastcopy "C:\...\FastCopy64.exe"`.

## Usar
```
pip install -e ".[dev]"
superfastfiles                      # janela
sff copy D:\Fotos E:\Backup         # cria E:\Backup\Fotos
sff sync D:\Projetos\ E:\Projetos --verify --exclude node_modules
```
Pacote portátil: `pip install -e ".[build]"` e `python tools/build.py`.
