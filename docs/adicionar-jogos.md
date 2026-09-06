# Adicionar novos jogos ao catálogo

Além dos jogos embutidos, você pode cadastrar qualquer servidor dedicado que tenha
manual oficial para Linux, desde que ele seja distribuído por um dos provedores
suportados. O jogo cadastrado passa a aparecer no menu e em todos os comandos
(`configure`, `install`, `switch`, `stop`, `backup`, `status`) como um jogo normal.

## Provedores suportados

| Provider | Como o download é feito | Como o processo é iniciado |
|---|---|---|
| `steam` | SteamCMD com login anônimo e o App ID do servidor dedicado | `executável` + `launch_args` + `extra_args` |
| `mojang` | Manifesto e JAR oficiais da Mojang (com verificação de SHA-1) | `java -Xmx<heap> -jar <executável> <launch_args>` |
| `hytale` | Downloader oficial da Hypixel Studios (OAuth interativo) | `java -Xmx<heap> -jar <executável> <launch_args>` |

Jogos custom usam um **perfil genérico**: nenhum argumento é inventado pelo código.
Você define os argumentos de inicialização em `launch_args` no JSON do jogo, a
partir do que o manual/pacote do servidor indicar.

## Cadastrar pelo menu (recomendado)

Execute o menu e escolha **"Adicionar novo jogo"**:

```bash
./start_server.sh
```

Ou diretamente:

```bash
./start_server.sh add-game
```

O cadastro é interativo e valida cada campo antes de gravar. Ele pergunta:

- **Identificador**: minúsculas, números, `-` ou `_` (2 a 32 caracteres). Não pode
  colidir com um jogo embutido.
- **Nome de exibição**: como aparece no menu e no site.
- **Provider**: `steam`, `mojang` ou `hytale`.
- **App ID** (só `steam`): o ID do *servidor dedicado* no Steam.
- **Executável**: caminho relativo dentro da release baixada (ex.: `PalServer.sh`).
  Não aceita caminho absoluto, `..` nem `\`.
- **Modo de parada**: veja a tabela abaixo.
- **Porta principal**.
- **Links de persistência** (opcional): pares origem-na-release → destino em `data/`,
  criados por link simbólico após o download (mantêm mundos/config fora das releases).

O jogo é gravado em `config/custom_games.json`. Em seguida, configure e instale:

```bash
./start_server.sh configure <id>
./start_server.sh install <id>
./start_server.sh switch <id>
```

## Modos de parada

Escolha conforme o que o servidor suporta para um encerramento com salvamento:

| Modo | Quando usar |
|---|---|
| `sigint` | O servidor salva ao receber Ctrl+C (SIGINT). |
| `console` | Há um comando de console (ex.: `stop`) enviado pelo tmux. |
| `source` | O servidor expõe Source RCON (TCP) para um comando de shutdown. |
| `web` | O servidor usa WebRCON (WebSocket), como Rust. Exige `python3-websocket`. |
| `hook` | Você fornece um executável local que faz o encerramento e é validado por você. |

O modo `hook` exige revisão manual: só inicia depois de você definir `stop_hook`
(caminho absoluto executável) e `shutdown_verified=true` no JSON, além de
`launch_args` revisados. O hook recebe `GAME_PID` e `GAME_DATA` no ambiente e deve
pedir uma saída normal, retornando código zero. Não existe hook padrão que use
`kill -9` — isso pode corromper o mundo.

## Formato do custom_games.json

Você também pode editar o arquivo à mão (com o jogo parado). Exemplo:

```json
{
  "palworld": {
    "name": "Palworld",
    "provider": "steam",
    "appid": "2394010",
    "executable": "PalServer.sh",
    "stop": "console",
    "port": 8211,
    "persistent": {
      "Pal/Saved": "Saved"
    }
  }
}
```

Regras de validação (aplicadas ao carregar e ao cadastrar):

- `id` não pode ser de um jogo embutido.
- `executable` e todos os caminhos de `persistent` são relativos, sem `..` nem `\`.
- `appid` (para `steam`) deve ser numérico.
- `provider` ∈ `steam`, `mojang`, `hytale`; `stop` ∈ `sigint`, `console`, `source`,
  `web`, `hook`.
- `port` entre 1 e 65535.

Uma entrada inválida faz o carregamento falhar com uma mensagem explicando o campo,
sem afetar os jogos embutidos.

## Ajustar a inicialização

Depois de `configure <id>`, edite `config/<id>.json` com o jogo parado:

- `launch_args`: lista de argumentos do servidor (ex.: `["-useperfthreads", "-NoAsyncLoadingThread"]`).
- `extra_args`: argumentos adicionais aplicados ao final.
- `java`/`heap`: para provedores `mojang`/`hytale` (ex.: `"heap": "6G"`). O campo
  `java` pode apontar para um JDK específico (por exemplo, gerenciado por SDKMAN;
  veja [Ubuntu e dependências](ubuntu.md)).
- `eula_accepted`: obrigatório `true` para provedores `mojang`.
- `rcon_password`/`rcon_port`: para os modos `source`/`web`.

## Limites

- A detecção de "servidores fora do gerenciador" cobre os jogos embutidos; um jogo
  custom rodando fora do gerenciador pode não ser detectado. Mantenha um único
  gerenciador.
- Para modos `source`/`web`, o gerenciador não sabe onde o servidor grava a config
  de RCON; habilite o RCON na configuração do próprio jogo (em `data/`).
- Valide sempre o encerramento e a persistência do mundo em um mundo descartável
  antes de colocar dados importantes sob gerenciamento.
