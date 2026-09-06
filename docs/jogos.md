# Provedores, configurações e encerramento

Separe a configuração do gerenciador
(`config/<jogo>.json`) da configuração lida pelo jogo (`games/<jogo>/data/`).
Edite ambas com o jogo parado. Os caminhos abaixo são relativos a `GAMES_ROOT`.

## Estratégia deste projeto

Não dependemos da promessa de que um atualizador manterá um arquivo personalizado.
Cada download ocorre em uma release nova. Configurações, mundos e mods ficam em
`data/`; o atualizador nunca recebe essa pasta como destino.

| Jogo | Configurações persistentes | Mundos e demais dados |
|---|---|---|
| Valheim | `config/valheim.json`; listas em `games/valheim/data/` | `games/valheim/data/worlds_local/` via `-savedir` |
| Conan | `games/conan/data/Saved/Config/LinuxServer/*.ini` | Todo `Saved/`, inclusive bancos e WAL; mods em `data/Mods/` |
| Rust | `games/rust/data/server/main/cfg/server.cfg` e `users.cfg` | Todo `data/server/`, identidade `main` |
| Minecraft Java | `games/minecraft/data/server.properties`, `eula.txt`, listas JSON | Diretório de trabalho `data/`, incluindo os mundos |
| Hytale | JSONs no diretório de trabalho `games/hytale/data/` | `universe/`, mods e credenciais no mesmo diretório |
| Smalland | Argumentos externos em `config/smalland.json` | `data/Saved/` ligado a `SMALLAND/Saved`; validar a versão |

O projeto conecta as pastas persistentes de Conan, Rust e Smalland por links
simbólicos **após** concluir o download. Defaults distribuídos pelo fornecedor
ficam preservados na release com sufixo `.vendor-defaults`, para comparação.
Não edite arquivos das releases nem os scripts distribuídos pelo Steam.

## SteamCMD

O gerenciador utiliza os App IDs dos **servidores dedicados**:

```bash
# Exemplo manual em uma pasta NOVA de download:
/usr/games/steamcmd \
  +@sSteamCmdForcePlatformType linux \
  +force_install_dir /caminho/absoluto/nova-release \
  +login anonymous \
  +app_update 896660 validate \
  +quit
```

Substitua o ID por `443030` (Conan), `258550` (Rust) ou `808040` (Smalland).
Use `force_install_dir` antes do login, como indicado pelo
[aviso do SteamCMD registrado na Valve](https://github.com/ValveSoftware/steam-for-linux/issues/8298).
O script usa `validate` porque sempre baixa em uma pasta isolada; não valida em
cima da instalação ativa. Confere também o manifesto e o executável esperado.

### Valheim

O jogo aceita `-savedir` para mundos e listas de acesso. O encerramento recomendado
é Ctrl+C; aqui é enviado SIGINT ao grupo exclusivo do jogo. O gerenciador aguarda
a saída antes do backup.
[Guia da Iron Gate](https://www.valheimgame.com/support/a-guide-to-dedicated-servers/).

No JSON, ajuste `server_name`, `world`, `password`, `port` e `public`.
`extra_args` permite, por exemplo, `["-crossplay"]`. O nome do mundo deve coincidir
com os arquivos migrados. O diretório anterior padrão era
`~/.config/unity3d/IronGate/Valheim`.

### Conan Exiles Enhanced

O App ID `443030` aceita login anônimo, documentado no
[manual técnico da Funcom](https://cdn.funcom.com/downloads/ConanExiles_TechManual.pdf).
O suporte Linux nativo foi anunciado nas
[notas do Enhanced](https://forums.funcom.com/t/conan-exiles-enhanced-patch-notes/296991).
Não selecione uma build Windows/Wine para esta integração.

O caminho `ConanSandbox/Saved/Config/LinuxServer` e o binário
`ConanSandboxServer-Linux-Shipping` correspondem à build Linux nativa. Toda a pasta
`Saved` é persistida, não somente `game.db`: uma instalação típica usa
`game_0.db`, além de arquivos SQLite `-wal` e `-shm`.

O adaptador envia `shutdown` por Source RCON, seguindo a implementação pública do
[adaptador Conan Enhanced do AMP](https://github.com/CubeCoders/AMPTemplates/blob/main/conan-exiles-enhanced.kvp).
Essa é uma referência de implementação, não uma garantia de teste no seu mundo.
Não inventamos um comando `save` genérico para Conan.

Ao iniciar, somente as chaves `RconEnabled`, `RconPort` e `RconPassword` da seção
`[RconPlugin]` em `Game.ini` são sincronizadas a partir do JSON privado. Configure
`rcon_password` e `rcon_port` nele. As demais opções INI permanecem intactas.
Nome público, senha de entrada, senha de administrador e regras de jogo devem
ser ajustados nos INIs; consulte a
[página da Funcom sobre configurações e portas](https://www.conanexiles.com/dedicated-servers/).
Ela ainda contém exemplos Windows: use `LinuxServer` nesta instalação.

### Rust vanilla

App ID `258550`, login anônimo. A Facepunch documenta `server/<identity>/cfg/server.cfg`
e informa que o console Linux exige RCON. Usamos a identidade `main` e persistimos
toda a árvore `server/`. A configuração do arquivo pode prevalecer sobre argumentos
da inicialização. [Guia da Facepunch](https://wiki.facepunch.com/rust/Creating-a-server).

`rcon.web`, `rcon.ip`, `rcon.port` e `rcon.password` são controlados pelo gerenciador.
As demais linhas de `server.cfg` são preservadas. Configure nesse arquivo o nome,
a descrição e regras; `max_players` no JSON fornece apenas o valor inicial.

O controle usa o [WebRCON da Facepunch](https://github.com/Facepunch/webrcon).
Envia `server.save`, aguarda a resposta, envia `quit` e aguarda o processo sair.
O salvamento final em `quit` também aparece no
[registro de desenvolvimento da Facepunch](https://commits.facepunch.com/matti/rust_reboot?p=2447).
Requer `python3-websocket`. Oxide/uMod/Carbon e atualizações de mods não estão
automatizados; não trate esta instalação vanilla como migração de servidor modificado.

## Minecraft Java vanilla

O provedor consulta o [manifesto da Mojang](https://piston-meta.mojang.com/mc/game/version_manifest_v2.json),
resolve `latest` para uma release ou usa `version` explícita, baixa os metadados e
o JAR e verifica seus SHA-1. O download exige `eula_accepted=true`, informado pelo
administrador após ler a [EULA](https://www.minecraft.net/eula).
Referência de execução: [download oficial do servidor](https://www.minecraft.net/en-us/download/server).

O JAR fica na release; o diretório de trabalho é `data/`. O instalador não copia
configurações sobre essa pasta. `server.properties` é criado somente se ausente;
edite nele a porta depois da primeira criação. `port` no JSON fornece o valor
inicial. Não use `level-name` apontando para fora de `data/`, pois o backup cobre
essa árvore. O console recebe `save-all flush` e `stop`, sem `/`.

A integração usa Java Edition, não Bedrock, Paper, Fabric ou Forge. Requisitos de
Java são conferidos pelos metadados; por exemplo, a
[release 26.1 exige Java 25](https://www.minecraft.net/en-us/article/minecraft-java-edition-26-1).
Não há downgrade automático de mundo ou versão após uma atualização malsucedida.

## Hytale

Obtenha o Downloader pelo [manual oficial da Hypixel Studios](https://support.hytale.com/hc/en-us/articles/45326769420827-Hytale-Server-Manual).
Extraia a ferramenta, leia seu `QUICKSTART.md` e informe o executável Linux em
`downloader`. A autenticação OAuth é interativa. Java 25 é necessário.

O script executa `-patchline release -download-path <arquivo>`, extrai o pacote
em uma nova release e inicia o JAR com `--assets` apontando para `Assets.zip`.
No projeto, `data/` é o diretório de trabalho: preserva `config.json`,
`permissions.json`, `bans.json`, `whitelist.json`, `universe/`, `mods/` e os
arquivos de autenticação. Edite configurações com o processo parado.

Após a primeira inicialização, abra o console e execute `/auth login device`.
O login do downloader e o do servidor são etapas distintas. O site indica somente
o processo, não a conclusão dessa autenticação. A porta padrão é UDP 5520.

Desabilitamos o atualizador interno com `HYTALE_DISABLE_UPDATES=1`; as atualizações
passam pelo menu e não disputam o gerenciamento de processos. O comando `stop`
inicia o encerramento, conforme a [API oficial HytaleServer](https://docs.hytale.com/api/com/hypixel/hytale/server/core/HytaleServer).

## Smalland — integração experimental

A publicadora anunciou a [ferramenta dedicada no Steam](https://store.steampowered.com/news/posts/?appgroupname=SMALLAND&appids=768200&enddate=1713799358&feed=steam_community_announcements).
O [adaptador público do AMP](https://github.com/CubeCoders/AMPTemplates/blob/main/smalland.kvp)
identifica o pacote `808040`, o binário Linux e a configuração por argumentos.
Ele usa `OS_CLOSE` para saída; isso não confirma um comando de console portátil
nem comprova o salvamento em uma versão Linux específica.

Por isso `install smalland` funciona, mas `start`/`switch` recusam iniciar por
padrão. Leia o script fornecido na release para montar `launch_args` e conferir
os caminhos realmente usados. O adaptador conecta `SMALLAND/Saved` a `data/Saved`.
Se a versão usar outro caminho, ajuste o adaptador antes de habilitar.

Para liberar, o administrador precisa testar salvamento/encerramento e restauração
em um mundo descartável, criar um executável local `stop_hook` e definir
`shutdown_verified=true`. O hook recebe `GAME_PID` e `GAME_DATA` no ambiente,
deve solicitar uma saída normal e retornar sucesso. O gerenciador ainda exige
término com código zero. **Não há hook padrão com `kill -9` ou `tmux kill-session`.**
Não copie credenciais EOS de tutoriais; use o pacote e as orientações atuais do fornecedor.
