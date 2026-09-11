# Games Server

Manual e menu em shell para um Ubuntu Server dedicado a jogos entre amigos:
instalar, atualizar, salvar/parar e trocar **um jogo por vez**, com console no
`tmux`, supervisão pelo `systemd` e uma página de consulta.

O menu Bash chama pequenos módulos Python para downloads, backup, controle de
processos e protocolos RCON. As credenciais e os mundos ficam fora do repositório.

## Situação da implementação

| Jogo | Instalação/atualização | Encerramento implementado |
|---|---|---|
| Valheim | SteamCMD, `896660`, Linux | SIGINT (Ctrl+C), espera do processo e backup |
| Conan Exiles Enhanced | SteamCMD, `443030`, Linux | `shutdown` por RCON local, espera e backup |
| Rust vanilla | SteamCMD, `258550`, Linux | `server.save` e `quit` por WebRCON local |
| Minecraft Java vanilla | Manifesto e JAR oficiais da Mojang | `save-all flush` e `stop` no console |
| Hytale | Downloader oficial com OAuth | `stop` no console |
| Smalland | SteamCMD, `808040`, Linux | **Experimental: exige hook de parada validado pelo administrador** |

Os adaptadores foram implementados a partir das fontes em [jogos](docs/jogos.md).
Os testes locais usam servidores simulados; ainda é necessário validar cada jogo
real, inclusive restauração dos mundos e conexão de jogadores. O gerenciador não
assume o controle de instalações já existentes automaticamente.

Além dos jogos embutidos, é possível **adicionar qualquer servidor dedicado** com
suporte a SteamCMD, Minecraft (Mojang) ou Hytale sem editar código; veja
[adicionar jogos](docs/adicionar-jogos.md).

## Começar

1. Prepare os pacotes com o [guia Ubuntu](docs/ubuntu.md).
2. Se já tem jogos rodando, leia [migração](docs/migracao.md) antes de usar o gerenciador.
3. Execute, como o usuário que será dono dos jogos:

```bash
chmod +x start_server.sh scripts/*.sh
./start_server.sh
```

O menu mostra o estado atual e a lista de jogos com indicadores (configurado,
instalado, ativo). Permite configurar um jogo, instalar/atualizar, escolher o jogo
ativo, parar, consultar status, abrir console, fazer backup e **adicionar um novo
jogo**. A primeira configuração pergunta os dados essenciais; revise o JSON gerado
para ajustes adicionais.

Exemplo sem menu:

```bash
./start_server.sh configure valheim
./start_server.sh install valheim
./start_server.sh switch valheim
./start_server.sh console
# Para sair do tmux sem parar o jogo: Ctrl+B, depois D.
./start_server.sh stop
./start_server.sh update valheim
./start_server.sh switch valheim
```

Em execução não interativa, `configure` cria um modelo **desabilitado**, sem
aceitar termos nem criar senhas. Edite o arquivo antes de continuar.

## Onde ficam os arquivos

Por padrão, `GAMES_ROOT=$HOME/.local/share/games-server`:

```text
games-server/
├── config/                 # JSONs privados: parâmetros, senhas, versão escolhida
├── games/<jogo>/
│   ├── current -> releases/release-...
│   ├── releases/           # Downloads e versões anteriores
│   ├── data/               # Mundos e configurações persistentes
│   └── logs/               # Saída do console por execução
├── backups/<jogo>/         # data + configuração do gerenciador + metadados
├── tools/                  # Estado privado dos provedores
└── runtime/                # Socket tmux, trava e estado dos processos
```

Para mudar a raiz, exporte `GAMES_ROOT` antes de configurar qualquer jogo e use o
mesmo valor na instalação dos serviços. **Mantenha uma única raiz e um único
usuário para gerenciar a máquina.** Não aponte para a pasta do Git.

Atualizações são baixadas em uma nova release, sem links para dados vivos.
Somente depois da validação são conectadas às pastas persistentes e ativadas por
uma troca de link. Isso consome mais disco e banda que uma atualização no lugar.
Não há limpeza automática de versões, downloads incompletos ou backups.

## Operação contínua e site

O `tmux` mantém o console após desconectar do SSH. Para recuperar o último jogo
selecionado após reinicialização e supervisionar falhas, configure os serviços
conforme [operação 24/7](docs/operacao.md).

```bash
python3 scripts/status_site.py
```

Acesse `http://127.0.0.1:8080` na máquina. A página lista os jogos configurados e
o **processo ativo**, sem afirmar que ele já aceita jogadores. Para acesso público,
siga [publicação do site](docs/site.md). Não há ações administrativas pelo site.

## Documentação

- [Ubuntu e dependências](docs/ubuntu.md)
- [Provedores, configurações e fontes por jogo](docs/jogos.md)
- [Adicionar novos jogos ao catálogo](docs/adicionar-jogos.md)
- [Modpacks de Minecraft (Forge) — montagem manual](docs/modpacks.md)
- [Operação, supervisão, backups e restauração](docs/operacao.md)
- [Migração das instalações existentes](docs/migracao.md)
- [Site público e rede](docs/site.md)
- [Arquitetura, testes e limites](docs/desenvolvimento.md)

## Verificar o código

```bash
bash -n start_server.sh scripts/start_server.sh scripts/install_systemd.sh
python3 -m unittest discover -s tests -v
```

Os testes não baixam jogos e não acessam o servidor remoto.
