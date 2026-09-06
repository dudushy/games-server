# Preparar o Ubuntu Server

Referência do projeto: Ubuntu Server **26.04 LTS, amd64**. Execute os jogos como
usuário comum dedicado (por exemplo `gameserver`). Use `sudo` somente para pacotes,
firewall e configuração do sistema.

## 1. Conferir recursos

```bash
cat /etc/os-release
uname -m
free -h
df -h
lsblk
```

Reserve espaço para dados, backups, versão atual e pelo menos uma nova cópia
completa de cada jogo. As releases anteriores permanecem no disco. O tamanho total
do disco não indica quanto está disponível em `/`: com LVM, o volume raiz pode ser
menor que o disco físico. Confira `df -h /` e planeje a expansão do LVM se
necessário (fora do escopo deste instalador).

## 2. Instalar ferramentas

```bash
sudo apt update
sudo apt install software-properties-common ca-certificates curl unzip \
  tmux python3 python3-websocket rsync zip
sudo add-apt-repository multiverse
sudo dpkg --add-architecture i386
sudo apt update
sudo apt install steamcmd
```

Leia e responda aos termos que o pacote SteamCMD apresentar. Não há aceitação
automática neste projeto. O executável costuma ficar em `/usr/games/steamcmd`.
O procedimento geral está na
[documentação do SteamCMD](https://developer.valvesoftware.com/wiki/SteamCMD).
Confira a disponibilidade dos pacotes na versão do seu Ubuntu antes de instalar.

## 3. Instalar o Java com SDKMAN (Minecraft, Hytale e jogos custom Java)

Os servidores Java (Minecraft, Hytale e jogos custom dos provedores `mojang`/`hytale`)
exigem um JDK. Neste projeto o Java é gerenciado com [SDKMAN](https://sdkman.io/) —
essa é a forma **principal e única** recomendada. O SDKMAN instala e troca JDKs por
usuário, sem `sudo`, e permite fixar a versão exata que cada jogo exige (por exemplo,
um jogo antigo que precisa de Java 17 e outro que precisa de Java 25) sem conflitar
entre si nem com o sistema.

O SDKMAN precisa do pacote `zip`/`unzip`, já incluídos na instalação de ferramentas
acima. Instale-o como o usuário dos jogos (nunca com `sudo`):

```bash
curl -s "https://get.sdkman.io" | bash
source "$HOME/.sdkman/bin/sdkman-init.sh"
sdk list java            # lista as distribuições disponíveis
sdk install java 25-tem  # exemplo: Temurin 25 (Minecraft 26.1+ exige Java 25)
java -version
```

Minecraft 26.1 passou a exigir Java 25, conforme as
[notas da Mojang](https://www.minecraft.net/en-us/article/minecraft-java-edition-26-1).
O instalador Minecraft lê o requisito de Java dos metadados da versão escolhida e
não fixa uma versão do jogo no código.

O SDKMAN instala em `~/.sdkman`; o `java` passa a apontar para a versão escolhida
naquele shell. **Para garantir que cada jogo use sempre a versão correta**
(inclusive sob o systemd, que não carrega o shell interativo), aponte o campo `java`
do JSON do jogo para o caminho absoluto do executável, por exemplo:

```json
"java": "/home/USUARIO/.sdkman/candidates/java/25-tem/bin/java"
```

Assim o jogo não depende do JDK padrão do shell. Confira a versão instalada com
`sdk current java` e a lista com `sdk list java`. Para instalar um segundo JDK
(ex.: `sdk install java 17-tem`), repita o comando e aponte o `java` de cada jogo
para o caminho correspondente.

Bibliotecas dos binários nativos variam por versão. Em caso de erro ao iniciar,
consulte o log e execute `ldd` no binário oficial já baixado. Instale os pacotes
correspondentes às bibliotecas ausentes. Não é necessário instalar Wine para a
versão Linux nativa de servidores que a ofereçam.

## 4. Escolher uma raiz persistente

```bash
export GAMES_ROOT="$HOME/.local/share/games-server"
```

Esse já é o padrão. Se usar outra pasta, mantenha o mesmo valor em todo terminal
e serviço. O script cria diretórios privados e usa `umask 077`. Execute o menu sem
`sudo`; misturar donos de arquivos causa falhas de atualização e salvamento.

## 5. Rede

Configure reserva DHCP/endereço estável na rede interna e encaminhe somente as
portas dos jogos escolhidos. O IP público fixo não substitui o encaminhamento.

| Jogo | Porta inicial usada pelos modelos |
|---|---|
| Valheim | UDP 2456–2457 |
| Conan | UDP 7777, 7778 e 27015; demais portas conforme recursos habilitados |
| Rust | UDP 28015 e 28017; Rust+ precisa de configuração adicional |
| Minecraft Java | TCP 25565 |
| Hytale | UDP 5520 |
| Smalland | Revisar o script distribuído e a versão antes de publicar |
| Jogos custom | Conforme o manual do servidor dedicado escolhido |

Fontes e particularidades estão em [jogos](jogos.md). RCON é administração:
não encaminhe 25575/28016 no roteador. Rust é configurado para RCON em loopback;
Conan pode escutar em todas as interfaces e precisa de bloqueio no firewall.

Antes de ativar um firewall remotamente, mantenha o SSH permitido e confira as
regras existentes para não se trancar para fora. Exemplo para uma nova máquina,
com SSH na porta padrão e Conan/Valheim:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 2456:2457/udp
sudo ufw allow 7777:7778/udp
sudo ufw allow 27015/udp
sudo ufw deny 25575/tcp
sudo ufw deny 28016/tcp
sudo ufw status verbose
# Só depois de revisar as regras e o acesso SSH:
sudo ufw enable
```

Não execute este exemplo cegamente sobre uma configuração de rede existente.
Para expor o site, consulte [site e rede](site.md).
