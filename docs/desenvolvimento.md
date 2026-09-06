# Arquitetura e validação

## Arquivos

| Arquivo | Responsabilidade |
|---|---|
| `start_server.sh` | Entrada na raiz do repositório |
| `scripts/start_server.sh` | Menu e encaminhamento dos comandos |
| `scripts/manager.py` | Trava, estado, processos, backup, importação e troca |
| `scripts/catalog.py` | Metadados/comandos por jogo e catálogo custom (merge com `config/custom_games.json`) |
| `scripts/providers.py` | SteamCMD, Mojang e Hytale Downloader |
| `scripts/rcon.py` | Source RCON e WebRCON local |
| `scripts/status_site.py` | Página e API somente de consulta |
| `scripts/install_systemd.sh` | Unidades de usuário, sem habilitação automática |

Python usa a biblioteca padrão, exceto `websocket-client` para Rust, disponível
no Ubuntu como `python3-websocket`. Bash não usa `eval`, e downloads não são
executados como scripts. O downloader Hytale é uma ferramenta externa instalada
explicitamente pelo administrador. `stop_hook` de Smalland é código local confiável.

## Estado e concorrência

Uma trava `flock` da biblioteca Python serializa as mutações por raiz. `desired.json`
registra o jogo escolhido; `blocked.json` impede a supervisão após falha de parada
ou inicialização. Arquivos JSON são escritos em temporários e renomeados.
O runner guarda PID, início do processo, boot ID e grupo/sessão para reduzir risco
de confundir um PID reutilizado. O snapshot privado da configuração identifica
como parar a execução atual mesmo se o JSON de configuração for editado.

Cada jogo é iniciado em um grupo próprio dentro do tmux. O runner aguarda também
processos restantes desse grupo antes de registrar a saída. Não damos suporte a
launchers que daemonizam ou criam processos fora desse grupo; adaptadores novos
devem executar o servidor em primeiro plano. A raiz e os scripts são controlados
pelo administrador, não por usuários do site.

## Instalação transacional

O download completo é feito em `releases/download-*`. Após validar o pacote,
criamos os links de persistência, renomeamos a release e substituímos `current`
atomicamente. Falha antes dessa substituição mantém a versão anterior. Falha de
execução após a ativação exige diagnóstico: não há rollback automático de mundos.

Metadados e JAR Minecraft são verificados pelos SHA-1 publicados pela Mojang.
SteamCMD valida os arquivos e o código confere manifesto completo e executável.
O ZIP Hytale é obtido pelo downloader e rejeita caminhos absolutos, `..` e links
simbólicos antes da extração. O código não dispõe de um checksum independente do
pacote Hytale; depende da ferramenta oficial e da validação de layout.

## Testes

```bash
bash -n start_server.sh scripts/start_server.sh scripts/install_systemd.sh
python3 -m unittest discover -s tests -v
```

Os testes criam dados descartáveis em `/tmp`, sockets locais e um socket tmux
exclusivo por teste. Precisam de permissão para abrir sockets/PTYs. Não usam o
tmux padrão do usuário nem baixam jogos. Cobrem falha de download, proteção de
configurações, checksum, EULA, concorrência, RCON fragmentado, rotas do site e
troca real entre processos simulados. Verificam também que timeout não mata o
processo anterior e que destino inválido não interrompe o jogo ativo.

## Limites que exigem validação real

- Instalar/iniciar cada build no Ubuntu alvo e conferir bibliotecas nativas.
- Testar saída, persistência do mundo e restauração com clientes reais por jogo.
- Conferir RCON Conan e Rust na versão instalada, com firewall aplicado.
- Completar os logins do Hytale e verificar persistência da autenticação após reboot.
- Validar o encerramento e os argumentos de Smalland antes de liberar o adaptador.
- Exercitar boot, parada do sistema e falha do processo sob systemd no servidor alvo.
- Definir retenção de logs/releases/backups e cópia externa de backups.

O site mede processo, não prontidão de protocolo. Os exemplos de rede não foram
aplicados ao roteador. O projeto não promete salvamento em corte de energia e
não migra automaticamente o serviço antigo do Conan.
