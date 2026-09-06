# Migrar Valheim e Conan existentes

Este guia cobre a migração de instalações antigas de Valheim e Conan para o
gerenciador. Antes de começar, levante os dados da instalação atual. Um exemplo
comum de inventário:

| Item | Onde costuma ficar |
|---|---|
| Usuário dos jogos | um usuário dedicado (ex.: `gameserver`) |
| Conan | `~/conan_server` ou o diretório usado no seu script de início |
| Inicialização Conan | um script próprio de início do servidor |
| Serviço antigo | uma unidade systemd, geralmente `Type=forking` |
| Console antigo | uma sessão `tmux` própria |
| Parada antiga | frequentemente `tmux kill-session`, sem salvamento explícito |
| Valheim | o diretório do servidor e o `run.sh` usados |
| Dados Valheim | `~/.config/unity3d/IronGate/Valheim` (padrão do jogo) |

Confirme os caminhos reais da sua máquina com `systemctl status`, `tmux ls` e
inspeção dos scripts antigos. O novo gerenciador não assume controle do processo
antigo automaticamente.

## 1. Preparar a janela de migração

Avise os jogadores e confira o console. Se a parada antiga do serviço Conan apenas
mata a sessão tmux, ela não faz salvamento explícito. **Não use `systemctl stop`
do serviço antigo como substituto de um procedimento de encerramento validado.**

Desabilitar o boot antigo sem parar o processo é uma ação separada:

```bash
sudo systemctl disable conan.service   # troque pelo nome real da sua unidade
```

Revise também a política de reinício antes da migração. Para impedir que o serviço
antigo reinicie o jogo após a saída, crie um override contendo:

```ini
[Service]
Restart=no
```

Use `sudo systemctl edit <sua-unidade>.service` e `sudo systemctl daemon-reload`.

Encerre o Conan por um procedimento de jogo já validado na instalação antiga.
Se RCON estiver habilitado, o novo adaptador usa `shutdown`; se não houver porta
RCON TCP escutando, ativá-la exige manutenção da instalação antiga — não basta
enviar comandos a uma porta fechada. Não edite INIs vivos esperando que a mudança
seja aplicada ou preservada no encerramento.

Antes de copiar, confirme a saída de todos os processos Conan e Valheim:

```bash
ps -eo pid,comm
tmux list-sessions
ss -lntu
```

Uma sessão vazia não prova que não há processos restantes. Faça uma cópia externa
dos dados antigos já parados antes de continuar.

## 2. Configurar e copiar os dados

No repositório, como o usuário dos jogos (substitua os caminhos de origem pelos da
sua máquina):

```bash
./start_server.sh configure valheim
./start_server.sh configure conan
./start_server.sh import-data valheim ~/.config/unity3d/IronGate/Valheim
./start_server.sh import-data conan ~/conan_server
./start_server.sh install valheim
./start_server.sh install conan
```

`import-data` copia, não move: Valheim recebe a árvore de dados informada; Conan
recebe `ConanSandbox/Saved` e, se existir, `ConanSandbox/Mods`. A origem permanece
intacta. Dados já existentes no destino causam recusa, para evitar sobreposição.

Ajuste `world` e `server_name` no Valheim para coincidir com o mundo que você quer
manter. Use sua senha real no JSON privado. Se o Conan já rodava com um número de
jogadores, porta e query específicos, ajuste esses valores no JSON; RCON recebe uma
senha própria nova, escolhida por você.

O comando `install` baixa a versão atual. Se houver migração de formato entre a
versão antiga e a atual, mantenha uma cópia dos dados e dos binários antigos para
retorno; não teste a atualização sobre sua única cópia do mundo.

## 3. Validar a migração

Inicie um jogo, entre com um cliente, confira construções/personagens e faça uma
mudança identificável. Pare pelo gerenciador, inicie novamente e confirme que a
mudança persistiu. Teste também a restauração de um backup em um mundo descartável.
Só então habilite [os serviços novos](operacao.md).

O detector de processos conhecidos impede iniciar enquanto enxergar o Conan
antigo, mas não é inventário universal: processos renomeados, outro usuário com
`/proc` restrito e containers podem escapar da detecção. Mantenha um único
gerenciador e desabilite quaisquer inicializadores antigos.
