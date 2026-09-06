# Operação, supervisão e recuperação

## Comandos

Execute na raiz do repositório como usuário dos jogos:

| Comando | Resultado |
|---|---|
| `./start_server.sh` | Menu interativo |
| `configure <jogo>` | Cria configuração sem sobrescrever uma existente |
| `install <jogo>` / `update <jogo>` | Backup, download isolado, validação e ativação da release |
| `start <jogo>` | Inicia somente se nenhum jogo gerenciado estiver vivo |
| `switch <jogo>` | Valida o destino, encerra o atual, faz backup e inicia o escolhido |
| `stop` | Solicita salvamento/saída e limpa a seleção de reinício automático |
| `status` | JSON sem segredos, com estado dos processos |
| `console` | Anexa ao tmux privado |
| `backup <jogo>` | Backup somente com o jogo parado |
| `import-data <jogo> <origem>` | Copia dados de Valheim/Conan sem sobrescrever dados existentes |
| `add-game` | Cadastra um jogo custom no catálogo (interativo); veja [adicionar jogos](adicionar-jogos.md) |

Nos exemplos da tabela, use `./start_server.sh` antes de cada comando.
`switch` não baixa um jogo ausente: configure e instale primeiro. Uma atualização
recusa alterar o jogo ativo; use `stop`, `update` e `switch` nessa ordem.
É possível baixar outro jogo enquanto o atual continua rodando, mas disco, CPU
e rede serão compartilhados.

## Como funciona a troca

1. Valida configuração, executável, Java e dependências de controle do destino.
2. Recusa avançar se detectar servidores conhecidos fora do gerenciador.
3. Desativa a seleção automática e registra a intenção de parada.
4. Envia o comando específico do jogo e aguarda o grupo de processos encerrar.
5. Confere o código de saída e cria um backup dos dados parados.
6. Inicia o destino em uma sessão `game` num socket tmux privado.

Se RCON falhar, houver timeout ou backup falhar, a operação termina com erro e
não inicia outro jogo. Não usamos `kill -9`, `pkill` ou `tmux kill-session` para
encerrar um jogo vivo. A limpeza de sessão só ocorre antes de iniciar, quando o
grupo anterior já não está vivo.

SIGINT do Valheim aceita códigos 0, 130 e sinal SIGINT; os demais adaptadores
exigem código zero. Isso confirma a saída normal do processo, **não prova sozinho
a integridade do mundo**. Confira logs e restauração em um mundo de teste antes
de colocar mundos importantes sob gerenciamento.

## Console e logs

```bash
./start_server.sh console
```

Desanexe com **Ctrl+B, depois D** — essa é a forma correta de sair do console
mantendo o jogo rodando. A saída também é gravada em
`games/<jogo>/logs/<execução>.log`. Logs podem conter informações privadas; não são
publicados pelo site. Se o processo já terminou, consulte o arquivo, pois a sessão
pode ter encerrado. Os logs não têm rotação automática nesta versão.

O monitor do jogo (o runner dentro do tmux) ignora **Ctrl+C**, **Ctrl+Z** e
**Ctrl+\\**. Se você apertar Ctrl+C por engano no console anexado, nem o jogo nem o
monitoramento são derrubados: o jogo roda isolado em sua própria sessão e o runner
continua acompanhando. Para parar um jogo, use sempre `./start_server.sh stop`
(ou `switch`), que faz o encerramento com salvamento e backup.

## Configurar o systemd

O supervisor verifica a cada 30 segundos se o último jogo selecionado morreu.
Se não houver bloqueio de segurança, tenta iniciá-lo novamente. Uma tentativa
que falha durante a inicialização cria um bloqueio para evitar repetição contínua.
Processo travado ainda vivo não é reiniciado automaticamente.

A forma mais simples de instalar, habilitar (com linger), parar, ver status e logs
dos serviços é pelo menu, em **"Site e serviços"** (`./start_server.sh` → opção 9).
Os passos manuais abaixo são equivalentes.

Com as instalações antigas já migradas/desabilitadas:

```bash
./scripts/install_systemd.sh
systemctl --user cat games-server.service games-status.service
# Execute como usuário dos jogos, conferindo o nome mostrado por whoami:
whoami
sudo loginctl enable-linger "$(whoami)"
systemctl --user enable --now games-server.service games-status.service
```

Se preferir, informe o nome do usuário explicitamente no lugar de `$(whoami)`.
O instalador de unidades cria os
arquivos em `~/.config/systemd/user/`, usa o caminho atual do repositório e não
habilita os serviços sozinho. Ele se recusa a sobrescrever unidades existentes.
Mantenha o repositório nesse caminho enquanto as unidades forem usadas.

Por padrão, o site de consulta escuta em `127.0.0.1:8080` (seguro, atrás de um
proxy reverso). Para gerar a unidade escutando em outro endereço/porta, defina as
variáveis antes de instalar:

```bash
STATUS_BIND=0.0.0.0 STATUS_PORT=8080 ./scripts/install_systemd.sh
```

Expor o site diretamente em `0.0.0.0` só é recomendado com HTTPS na frente; veja
[site e rede](site.md).

O linger permite manter o gerenciador de usuário sem uma sessão SSH aberta.
Referência: [manual loginctl do systemd](https://www.freedesktop.org/software/systemd/man/latest/loginctl.html).

```bash
systemctl --user status games-server.service
journalctl --user -u games-server.service -n 100
```

`ExecStop` usa a mesma parada segura, aguardando operações concorrentes terminarem.
Preserva a seleção para o próximo início do serviço. O supervisor fica bloqueado
durante essa parada, para não ressuscitar o jogo antes de sair.

A unidade usa `KillMode=process` e `SendSIGKILL=no`: uma falha de parada não deve
ser convertida em morte forçada do jogo pelo serviço. Essa escolha pode deixar
processos vivos se `ExecStop` falhar; confira `status` e os logs. Em um desligamento
do **sistema operacional**, fases posteriores ainda podem terminar processos
restantes. Não existe garantia de salvamento durante queda de energia; UPS e
backups externos continuam relevantes.

`stop` pelo menu limpa a seleção: nenhum jogo volta sozinho. `systemctl --user
stop games-server` mantém a seleção para quando o serviço for iniciado novamente.
Se uma parada falhar, resolva o motivo e repita `stop` antes de uma nova troca.

## Backups

Os backups incluem `data/`, o JSON privado do gerenciador e os metadados da release.
As credenciais fazem parte desse backup. Binários ficam nas releases, não no tar.
Não há exclusão de backups antigos: acompanhe o espaço e copie backups para outro
disco/máquina. Uma cópia no mesmo disco não protege contra falha física.

```bash
./start_server.sh stop
./start_server.sh backup conan
tar -tzf /caminho/backup.tar.gz
```

O backup recusa links simbólicos dentro de `data/` para não omitir mundos externos.
Os links das releases ficam fora de `data/`. Imports também recusam links e
preservam a origem. Não faça cópia isolada de um banco SQLite aberto.

## Restaurar

Use somente um arquivo produzido por este projeto e inspecionado. Primeiro pare
o jogo e o supervisor, preserve o estado atual e extraia o backup numa pasta vazia:

```bash
./start_server.sh stop
systemctl --user stop games-server.service
mkdir /tmp/games-restore
tar -xzf /caminho/backup.tar.gz -C /tmp/games-restore
```

Confira `data/`, `config.json` e `release.json` extraídos. Mova a `data/` atual para
um nome de reserva e coloque a restaurada no caminho original, mantendo o dono.
Restaure o JSON apenas se quiser recuperar também parâmetros e senhas anteriores.
Os links das releases continuarão apontando para o mesmo caminho `data/`.

Se precisar de uma versão antiga, escolha a release compatível e troque `current`
com o jogo parado. **Reverter apenas os binários não desfaz migrações do mundo**:
use juntos o backup e a versão correspondente. Nunca remova a release apontada
por `current`. Reinicie o jogo, confira o mundo e teste uma conexão antes de
reativar o supervisor.
