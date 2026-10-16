<div align="center">

# ⚡ SuperFastFiles

**Copiador de arquivos rápido, simples de verdade.**
Desktop · Portátil · Inspirado no [FastCopy](https://fastcopy.jp).

![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/PySide6-Qt%206-41CD52?logo=qt&logoColor=white)
![Status](https://img.shields.io/badge/status-0.2.0-E09A0A)
![Plataforma](https://img.shields.io/badge/Windows%20%7C%20Linux%20%7C%20macOS-0078D6?logo=windows&logoColor=white)
![Idiomas](https://img.shields.io/badge/idiomas-PT%20%7C%20EN%20%7C%20ES-6c6e72)

</div>

---

## Sobre

O **SuperFastFiles** copia, move, sincroniza e apaga arquivos o mais rápido que o disco aguenta — e sem
complicação. Ele descobre sozinho se a origem e o destino são SSD, HD, rede ou o mesmo disco e escolhe a melhor
forma de copiar. Linguagem simples, ajuda em cada opção (ícone **?**) e o mesmo visual do IGNF Finora.

- ⚡ **Rápido** — empata ou ganha do FastCopy nos testes (veja [Desempenho](#desempenho))
- 🔒 **Local e portátil** — não instala nada, não acessa a internet, tudo numa pasta só
- 🛡️ **Seguro** — Sincronizar e Apagar pedem confirmação; **Simular** mostra tudo antes de fazer
- ✅ **Verificação** — relê cada arquivo gravado e confere com hash xxh3-128
- 🌗 **Tema claro e escuro** com acento âmbar · 🌎 **Português, inglês e espanhol**

## Funcionalidades

| Módulo | O que faz |
|---|---|
| **Copiar** | Arraste arquivos e pastas · copiar, mover, sincronizar ou apagar · só os diferentes, só os mais novos ou sempre · filtros (incluir/ignorar) · velocidade, tempo restante e gráfico ao vivo · pausar e cancelar |
| **Simular** | Lista o que seria copiado, sobrescrito ou apagado, sem alterar nada |
| **Fila** | Guarda tarefas para rodarem uma depois da outra |
| **Histórico** | Cada tarefa feita, com tempo, velocidade e erros |
| **Log** | Estratégia usada, erros e itens ignorados da última tarefa · copiar ou salvar |
| **Configurações** | Tema, idioma, aviso ao terminar, tipo de disco, threads e tamanho do bloco |
| **Modo servidor*** | Leva junto permissões (ACL) e dados extras (fluxos alternativos / xattr) |
| **Linha de comando** | `sff copy`, `move`, `sync`, `delete` — as mesmas opções da janela |

<sub>* desligado por padrão — veja [Modo servidor](#modo-servidor).</sub>

## Baixar

Na página [Releases](https://github.com/igonozoid/SuperFastFiles/releases), baixe o `.zip` do seu sistema,
descompacte onde quiser e abra o **SuperFastFiles**. Não precisa instalar nem ser administrador. Preferências e
histórico ficam na pasta `data`, ao lado do programa — para remover, apague a pasta inteira.

## É seguro?

> ⚠️ **"O Windows protegeu o computador"** — esse aviso do SmartScreen aparece para todo programa sem assinatura
> digital paga e com poucos downloads. Ele **não** quer dizer que um vírus foi encontrado.
> Para abrir: **Mais informações › Executar assim mesmo** (só na primeira vez).
> Dica: antes de descompactar, botão direito no `.zip` › Propriedades › **Desbloquear** › OK.

| | |
|---|---|
| 📖 **Código-fonte público** | Tudo o que o programa faz está neste repositório; o pacote é gerado dele por `tools/build.py` |
| 🌐 **Sem internet** | Não envia nem baixa nada, não instala nada, não pede administrador, não mexe no Registro |
| 📁 **Só o que você escolher** | Lê e grava apenas as pastas da tarefa; Sincronizar e Apagar sempre pedem confirmação |
| 🔍 **Confira o download** | Compare com o `SHA256SUMS.txt` da versão: `Get-FileHash .\SuperFastFiles-*.zip` (PowerShell) ou `sha256sum` |
| 🧪 **Segunda opinião** | Envie o `.zip` ao [VirusTotal](https://www.virustotal.com) — programas em Python às vezes levam alarme falso de 1 ou 2 antivírus menos conhecidos |

macOS: na primeira vez, botão direito no programa › **Abrir** › **Abrir**. O mesmo texto vai dentro do pacote,
no `LEIA-ME.txt` (português, inglês e espanhol).

## Modo servidor

Desligado por padrão — para uso pessoal não faz diferença. Ligue a opção **Modo servidor: copiar permissões e
dados extras** (ou `sff ... --server`) em servidores de arquivos e backups de empresa:

| Sistema | O que vai junto |
|---|---|
| Windows | Permissões (ACL) e fluxos alternativos (ADS) |
| Linux | Atributos estendidos (xattr, incluindo as ACLs POSIX) |
| macOS | ACL e atributos estendidos |

Para copiar também o **dono** original, abra o programa como administrador (Windows) ou root (Linux/macOS).

## Desempenho

Ele mede os discos e escolhe a estratégia: **mesmo HD** → sequencial com blocos grandes; **HD** → poucas threads;
**SSD** → muitas threads; **rede** → muitas threads e cópia no servidor. Arquivos grandes vão por um pipeline
(uma thread lê enquanto outra grava) sem cache do sistema, como o FastCopy; arquivos pequenos usam a cópia do
próprio sistema em paralelo; e, quando o disco permite, a cópia é instantânea (reflink, clonefile).

Windows 11 · `tools/bench.py` · mediana de 2–3 rodadas · FastCopy 5.11.3 com `/no_ui`, sem verificação.

**NVMe → HD externo USB (Samsung M3 Portable)**

| Conjunto | SuperFastFiles | FastCopy | robocopy /MT:32 |
|---|:---:|:---:|:---:|
| 20.000 arquivos de 8 KB | 318 arq/s | 313 arq/s | 325 arq/s |
| 3.000 arquivos mistos (3,9 GB) | **39,3 MB/s** | 29,0 MB/s | 18,4 MB/s |
| 1 arquivo de 4 GB | **58,9 MB/s** | 39,9 MB/s | 68,6 MB/s ¹ |

**Mesmo NVMe (origem e destino no mesmo disco)**

| Conjunto | SuperFastFiles | robocopy /MT:32 |
|---|:---:|:---:|
| 20.000 arquivos de 8 KB | **4.305 arq/s** | 2.809 arq/s |
| 3.000 arquivos mistos (3,9 GB) | 113 MB/s | 117 MB/s |

<sub>¹ O robocopy grava pelo cache do Windows e termina antes de tudo chegar ao disco; o SuperFastFiles e o
FastCopy gravam direto no disco e só terminam com o arquivo gravado. Arquivos pequenos no HD e o conjunto misto
no NVMe empatam porque o limite é o próprio disco.</sub>

Comparar na sua máquina:
`python tools/bench.py --work C:\bench --dest K:\bench --fastcopy "C:\...\FastCopy64.exe"`

## Começando (código-fonte)

**Requisitos:** Windows 10/11, Linux ou macOS · Python 3.12+ (oficial, de [python.org](https://www.python.org/downloads/))

```powershell
git clone https://github.com/igonozoid/SuperFastFiles.git
cd SuperFastFiles
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m superfastfiles
```

> 💡 Se o PowerShell bloquear o script de ativação:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

Linha de comando:

```powershell
sff copy D:\Fotos E:\Backup                       # cria E:\Backup\Fotos
sff sync D:\Projetos\ E:\Projetos --verify --exclude node_modules
sff --lang en delete E:\Lixo --dry-run
```

Pacote portátil: `python -m pip install -e ".[build]"` e `python tools/build.py` → `dist/` (pasta, `.zip` e
`SHA256SUMS.txt`).

## Estrutura do projeto

```
SuperFastFiles/
├── data/                  # preferências, histórico e log (ignorado pelo Git)
├── packaging/             # PyInstaller e LEIA-ME do pacote
├── src/superfastfiles/
│   ├── __main__.py        # ponto de entrada (janela)
│   ├── cli.py             # linha de comando (sff)
│   ├── i18n.py            # idiomas
│   ├── assets/            # fontes IBM Plex e traduções (locales/*.json)
│   ├── core/              # pastas, configurações, log, dados da empresa
│   ├── engine/            # motor de cópia (sem Qt): varredura, estratégia, cópia por sistema
│   ├── services/          # fila e histórico
│   └── ui/                # janela, telas e tema (PySide6, padrão Finora)
├── tests/
├── tools/                 # build.py, bench.py, i18n.py
├── CLAUDE.md              # guia para desenvolvimento assistido
└── pyproject.toml
```

## Stack

- **[PySide6](https://doc.qt.io/qtforpython-6/)** — interface nativa Qt 6
- **[QtAwesome](https://github.com/spyder-ide/qtawesome)** — ícones Font Awesome
- **[xxhash](https://github.com/ifduyue/python-xxhash)** — verificação xxh3-128
- **APIs do sistema via ctypes** — Win32 (CopyFileEx, E/S sem cache), `copy_file_range`/reflink (Linux),
  `clonefile`/`copyfile` (macOS)
- **PyInstaller** — pacote portátil

## Roadmap

- [x] Motor de cópia com estratégia por disco e E/S sem cache
- [x] Copiar, mover, sincronizar e apagar, com filtros, simulação e verificação
- [x] Janela no padrão Finora: fila, histórico, log, tema claro/escuro
- [x] Linha de comando (`sff`)
- [x] Português, inglês e espanhol
- [x] Benchmark contra FastCopy e robocopy
- [x] Modo servidor (permissões e dados extras)
- [x] Pacote portátil com verificação SHA-256
- [ ] Medir desempenho no Linux e no macOS
- [ ] "Enviar para" / menu de contexto do Explorer

## Licença

© 2026 IGNF Projetos e Serviços de Engenharia LTDA. Todos os direitos reservados.
Desenvolvido por [IGNF Engenharia](https://ignf.com.br) · [IGNF LAB](https://ignf.com.br/ignf-lab/).
