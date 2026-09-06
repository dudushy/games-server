#!/usr/bin/env bash
# Menu interativo do gerenciador de servidores de jogos.
# Sem eval, sem dependências além de bash, tmux e python3 (já exigidos pelo projeto).
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MANAGER=("python3" "$SCRIPT_DIR/manager.py")

# Repasse direto: qualquer argumento vai para o manager (modo não interativo).
if (($#)); then
  exec "${MANAGER[@]}" "$@"
fi

# A partir daqui o script é uma TUI interativa. Sob 'set -e', qualquer comando que
# retorne código != 0 (um sudo cancelado, um systemctl sem unidade, um curl de teste
# que falha, um grep sem correspondência) encerraria o menu inteiro. Isso é indesejado
# numa interface interativa, então desativamos o errexit aqui. Mantemos 'nounset' e
# 'pipefail'. Cada ação trata seus próprios erros e exibe mensagens ao usuário.
set +e

# Cores só quando a saída é um terminal; caso contrário, strings vazias.
if [[ -t 1 ]]; then
  BOLD=$'\e[1m'; DIM=$'\e[2m'; RESET=$'\e[0m'
  RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; BLUE=$'\e[34m'; CYAN=$'\e[36m'
else
  BOLD=""; DIM=""; RESET=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; CYAN=""
fi

# IDs dos jogos em ordem estável, lidos do status.
GAME_IDS=()

pause() {
  printf '\n%sPressione Enter para continuar...%s' "$DIM" "$RESET"
  read -r _ || true
}

# Extrai campos do status JSON usando python3 (evita parser JSON frágil em bash).
# Uso: status_field <expressão python sobre a variável data>
status_json() {
  "${MANAGER[@]}" status 2>/dev/null || echo '{}'
}

render_header() {
  local data="$1"
  clear 2>/dev/null || printf '\n'
  printf '%s══════════════════════════════════════════════%s\n' "$CYAN" "$RESET"
  printf '%s  Games Server%s\n' "$BOLD" "$RESET"
  printf '%s══════════════════════════════════════════════%s\n' "$CYAN" "$RESET"
  # Estado global e jogo ativo.
  python3 - "$data" <<'PY'
import json, sys
data = json.loads(sys.argv[1] or "{}")
state = data.get("state", "desconhecido")
active = data.get("active_game")
labels = {"running": "\033[32mem execução\033[0m",
          "stopped": "\033[33mparado\033[0m",
          "attention": "\033[31matenção necessária\033[0m"}
print(f"  Estado: {labels.get(state, state)}")
print(f"  Jogo ativo: {active if active else '—'}")
if data.get("external_processes_detected"):
    print("  \033[31m! Servidor fora do gerenciador detectado\033[0m")
PY
  printf '%s──────────────────────────────────────────────%s\n' "$CYAN" "$RESET"
}

# Lista os jogos com indicadores e preenche GAME_IDS na mesma ordem exibida.
render_games() {
  local data="$1"
  mapfile -t GAME_IDS < <(python3 - "$data" <<'PY'
import json, sys
data = json.loads(sys.argv[1] or "{}")
for g in data.get("games", []):
    print(g["id"])
PY
)
  printf '%s  Jogos:%s\n' "$BOLD" "$RESET"
  python3 - "$data" <<'PY'
import json, sys
data = json.loads(sys.argv[1] or "{}")
active = data.get("active_game")
G, Y, R, D, X = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"
games = data.get("games", [])
if not games:
    print("    (nenhum jogo no catálogo)")
for i, g in enumerate(games, 1):
    if not g["configured"]:
        tag = f"{D}não configurado{X}"
    elif not g["enabled"]:
        tag = f"{D}desabilitado{X}"
    elif not g["installed"]:
        tag = f"{Y}instalação pendente{X}"
    elif g["experimental"]:
        tag = f"{Y}validação pendente{X}"
    elif g["id"] == active:
        tag = f"{G}● ativo{X}"
    else:
        tag = f"{G}instalado{X}"
    print(f"    {i:>2}) {g['name']:<28} {tag}")
PY
  printf '%s──────────────────────────────────────────────%s\n' "$CYAN" "$RESET"
}

# Solicita a escolha de um jogo pelo número exibido; ecoa o id em stdout.
choose_game() {
  local prompt="$1" index
  read -r -p "$prompt" index || return 1
  [[ "$index" =~ ^[0-9]+$ ]] || { printf '%sNúmero inválido.%s\n' "$RED" "$RESET" >&2; return 1; }
  ((index >= 1 && index <= ${#GAME_IDS[@]})) || { printf '%sFora da faixa.%s\n' "$RED" "$RESET" >&2; return 1; }
  printf '%s' "${GAME_IDS[index-1]}"
}

run_manager() {
  # Executa o manager mostrando erros sem derrubar o menu.
  if ! "${MANAGER[@]}" "$@"; then
    printf '\n%sOperação não concluída; leia a mensagem acima.%s\n' "$YELLOW" "$RESET"
  fi
}

game_submenu() {
  local action_label="$1"; shift
  local action="$1"
  local data game
  data="$(status_json)"
  render_games "$data"
  ((${#GAME_IDS[@]})) || { printf '%sNenhum jogo disponível.%s\n' "$YELLOW" "$RESET"; pause; return; }
  game="$(choose_game "Número do jogo para ${action_label}: ")" || { pause; return; }
  run_manager "$action" "$game"
  pause
}

add_game_flow() {
  printf '\n%sCadastro de novo jogo (SteamCMD, Minecraft/Mojang ou Hytale).%s\n' "$BOLD" "$RESET"
  printf '%sResponda as perguntas; a entrada é validada antes de gravar.%s\n\n' "$DIM" "$RESET"
  run_manager add-game
  pause
}

# ─────────────────────────── Site e serviços ───────────────────────────

# Nomes fixos usados pelo instalador de unidades e pela config do Nginx.
NGINX_SITE_NAME="games-status"

# Confirma uma ação com o usuário (retorna 0 se sim).
confirm() {
  local answer
  read -r -p "$1 [s/N]: " answer || return 1
  [[ "${answer,,}" == "s" ]]
}

# Detecta o IP da LAN (rota padrão) e o IP público (via serviço externo).
lan_ip() {
  ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}'
}
public_ip() {
  # Tenta alguns serviços; silencioso em falha (o usuário pode informar à mão).
  curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null \
    || curl -fsS --max-time 5 https://ifconfig.me 2>/dev/null \
    || true
}

# Executa um comando com sudo, mostrando-o antes.
run_sudo() {
  printf '%s$ sudo %s%s\n' "$DIM" "$*" "$RESET"
  sudo "$@"
}

svc_install() {
  local bind port
  printf '\n%sGerar unidades systemd (gerenciador + site).%s\n' "$BOLD" "$RESET"
  printf 'Bind do site: 1) 127.0.0.1 (padrão, atrás de proxy)  2) 0.0.0.0 (exposição direta)\n'
  read -r -p 'Opção [1]: ' b || return
  case "$b" in 2) bind="0.0.0.0" ;; *) bind="127.0.0.1" ;; esac
  read -r -p 'Porta do site [8080]: ' port || return
  [[ "$port" =~ ^[0-9]+$ ]] || port=8080
  local units="$HOME/.config/systemd/user"
  if [[ -e "$units/games-server.service" || -e "$units/games-status.service" ]]; then
    printf '%sUnidades já existem.%s\n' "$YELLOW" "$RESET"
    if confirm 'Regenerar (remove e recria as unidades)?'; then
      systemctl --user stop games-server.service games-status.service 2>/dev/null || true
      rm -f "$units/games-server.service" "$units/games-status.service"
      systemctl --user daemon-reload 2>/dev/null || true
    else
      pause; return
    fi
  fi
  STATUS_BIND="$bind" STATUS_PORT="$port" bash "$SCRIPT_DIR/install_systemd.sh" \
    || printf '%sFalha ao gerar unidades.%s\n' "$RED" "$RESET"
  pause
}

svc_enable() {
  printf '\n%sHabilitar e iniciar os serviços (com linger).%s\n' "$BOLD" "$RESET"
  printf '%sO linger mantém os serviços após você sair do SSH; exige sudo.%s\n' "$DIM" "$RESET"
  run_sudo loginctl enable-linger "$(whoami)" \
    || { printf '%sNão foi possível habilitar o linger.%s\n' "$RED" "$RESET"; pause; return; }
  systemctl --user enable --now games-server.service games-status.service \
    && printf '%sServiços habilitados e iniciados.%s\n' "$GREEN" "$RESET" \
    || printf '%sFalha ao habilitar/iniciar; confira o status.%s\n' "$RED" "$RESET"
  pause
}

svc_stop() {
  systemctl --user stop games-server.service games-status.service \
    && printf '%sServiços parados (seleção de jogo preservada).%s\n' "$GREEN" "$RESET" \
    || printf '%sFalha ao parar.%s\n' "$RED" "$RESET"
  pause
}

svc_disable() {
  systemctl --user disable --now games-server.service games-status.service \
    && printf '%sServiços desabilitados.%s\n' "$GREEN" "$RESET" \
    || printf '%sFalha ao desabilitar.%s\n' "$RED" "$RESET"
  pause
}

svc_status() {
  printf '\n%s── games-server ──%s\n' "$CYAN" "$RESET"
  systemctl --user --no-pager status games-server.service 2>&1 | head -12 || true
  printf '\n%s── games-status (site) ──%s\n' "$CYAN" "$RESET"
  systemctl --user --no-pager status games-status.service 2>&1 | head -12 || true
  pause
}

svc_logs() {
  printf 'Logs de: 1) gerenciador  2) site\n'
  read -r -p 'Opção [1]: ' l || return
  local unit=games-server.service
  [[ "$l" == 2 ]] && unit=games-status.service
  journalctl --user -u "$unit" -n 80 --no-pager 2>&1 || \
    printf '%sSem logs (serviço nunca iniciou?).%s\n' "$YELLOW" "$RESET"
  pause
}

site_test() {
  local bind port
  printf '\n%sTeste do site em primeiro plano (Ctrl+C encerra o teste).%s\n' "$BOLD" "$RESET"
  # Se o serviço já estiver ativo, o site já está no ar — testar aqui colidiria na porta.
  if systemctl --user is-active --quiet games-status.service 2>/dev/null; then
    printf '%sO serviço games-status já está ativo — o site já está no ar.%s\n' "$YELLOW" "$RESET"
    printf 'Acesse via túnel SSH: %sssh -L 8080:127.0.0.1:8080 <usuario>@<servidor>%s\n' "$DIM" "$RESET"
    printf 'Depois abra http://127.0.0.1:8080\n'
    printf 'Para testar em primeiro plano, pare o serviço antes (opção 3) ou use outra porta.\n'
    if ! confirm 'Tentar mesmo assim (em outra porta)?'; then pause; return; fi
  fi
  printf 'Bind: 1) 127.0.0.1 (use túnel SSH)  2) 0.0.0.0 (LAN)\n'
  read -r -p 'Opção [1]: ' b || return
  case "$b" in 2) bind="0.0.0.0" ;; *) bind="127.0.0.1" ;; esac
  read -r -p 'Porta [8080]: ' port || return
  [[ "$port" =~ ^[0-9]+$ ]] || port=8080
  if [[ "$bind" == "127.0.0.1" ]]; then
    printf '%sDo seu computador:%s ssh -L %s:127.0.0.1:%s <usuario>@<servidor>\n' "$DIM" "$RESET" "$port" "$port"
    printf 'Depois abra http://127.0.0.1:%s\n\n' "$port"
  else
    local lip; lip="$(lan_ip)"
    printf 'Na LAN, acesse http://%s:%s\n\n' "${lip:-<ip-do-servidor>}" "$port"
  fi
  python3 "$SCRIPT_DIR/status_site.py" --bind "$bind" --port "$port" || true
  pause
}

# Fluxo de publicação: HTTPS público (nginx + certbot) ou HTTP LAN.
site_publish() {
  printf '\n%sPublicar o site.%s\n' "$BOLD" "$RESET"
  printf 'Como o HTTPS/entrada pública será feito?\n'
  printf '  1) %sAtrás de um proxy reverso externo%s (Caddy/nginx em outra máquina) — recomendado\n' "$BOLD" "$RESET"
  printf '  2) HTTPS neste próprio servidor (instala nginx + certbot aqui)\n'
  printf '  3) Somente LAN (HTTP, sem proxy)\n'
  read -r -p 'Opção [1]: ' scope || return
  case "$scope" in
    2) site_publish_public ;;
    3) site_publish_lan ;;
    *) site_publish_proxy ;;
  esac
}

# Cenário recomendado: outro host (ex.: um Raspberry Pi com Caddy) termina o TLS e
# faz o proxy até este servidor. Aqui só expomos o site na LAN e mostramos a config
# pronta para colar no proxy.
site_publish_proxy() {
  local port lip
  printf '\n%sPublicação atrás de proxy reverso externo.%s\n' "$BOLD" "$RESET"
  printf '%sO proxy (Caddy/nginx em outra máquina) termina o HTTPS e encaminha até aqui.%s\n' "$DIM" "$RESET"
  read -r -p 'Porta do site nesta máquina [8080]: ' port || return
  [[ "$port" =~ ^[0-9]+$ ]] || port=8080
  # O proxy precisa alcançar o site pela rede: bind em 0.0.0.0 (não loopback).
  local units="$HOME/.config/systemd/user"
  systemctl --user stop games-status.service 2>/dev/null
  rm -f "$units/games-server.service" "$units/games-status.service" 2>/dev/null
  systemctl --user daemon-reload 2>/dev/null
  STATUS_BIND="0.0.0.0" STATUS_PORT="$port" bash "$SCRIPT_DIR/install_systemd.sh" \
    || { printf '%sFalha ao gerar unidades.%s\n' "$RED" "$RESET"; pause; return; }
  run_sudo loginctl enable-linger "$(whoami)"
  systemctl --user enable --now games-server.service games-status.service
  lip="$(lan_ip)"
  printf '\n%s✔ Site exposto na LAN em %s:%s (HTTP).%s\n' "$GREEN" "${lip:-<ip-deste-servidor>}" "$port" "$RESET"
  printf '\n%sNo host do proxy, aponte o domínio para este servidor.%s\n' "$BOLD" "$RESET"
  printf '\n%sExemplo para Caddy%s (/etc/caddy/Caddyfile):\n' "$CYAN" "$RESET"
  printf '  %sseu-dominio.exemplo {\n      reverse_proxy %s:%s\n  }%s\n' "$DIM" "${lip:-<ip-deste-servidor>}" "$port" "$RESET"
  printf 'Recarregue o proxy: %ssudo systemctl reload caddy%s\n' "$DIM" "$RESET"
  printf '\n%sExemplo para nginx%s (bloco server, dentro de um host com HTTPS):\n' "$CYAN" "$RESET"
  printf '  %slocation / { proxy_pass http://%s:%s; proxy_set_header Host $host; }%s\n' "$DIM" "${lip:-<ip-deste-servidor>}" "$port" "$RESET"
  printf '\n%sNo modem, encaminhe 80/443 para o host do PROXY (não para este servidor).%s\n' "$YELLOW" "$RESET"
  printf 'Crie o registro DNS do domínio apontando para seu IP público.\n'
  printf '%sO certificado HTTPS é responsabilidade do proxy (o Caddy emite automaticamente).%s\n' "$DIM" "$RESET"
  pause
}

site_publish_lan() {
  local port lip
  read -r -p 'Porta do site na LAN [8080]: ' port || return
  [[ "$port" =~ ^[0-9]+$ ]] || port=8080
  printf '\n%sConfigurando o site para escutar na LAN (0.0.0.0:%s).%s\n' "$BOLD" "$port" "$RESET"
  # Gera/atualiza a unidade com bind 0.0.0.0 e (re)inicia.
  local units="$HOME/.config/systemd/user"
  systemctl --user stop games-status.service 2>/dev/null || true
  rm -f "$units/games-server.service" "$units/games-status.service" 2>/dev/null || true
  systemctl --user daemon-reload 2>/dev/null || true
  STATUS_BIND="0.0.0.0" STATUS_PORT="$port" bash "$SCRIPT_DIR/install_systemd.sh" || {
    printf '%sFalha ao gerar unidades.%s\n' "$RED" "$RESET"; pause; return; }
  run_sudo loginctl enable-linger "$(whoami)" || true
  systemctl --user enable --now games-status.service || true
  lip="$(lan_ip)"
  printf '\n%s✔ Site publicado na LAN.%s\n' "$GREEN" "$RESET"
  printf '  Acesse de qualquer dispositivo da rede: %shttp://%s:%s%s\n' "$BOLD" "${lip:-<ip-do-servidor>}" "$port" "$RESET"
  printf '  Sem HTTPS e sem acesso externo (apenas rede local).\n'
  pause
}

site_publish_public() {
  local domain lan pub
  read -r -p 'Domínio (ex.: status.seu-dominio.exemplo): ' domain || return
  [[ -n "$domain" ]] || { printf '%sDomínio obrigatório.%s\n' "$RED" "$RESET"; pause; return; }
  lan="$(lan_ip)"; pub="$(public_ip)"

  # Pré-requisitos externos PRECISAM estar prontos ANTES do certbot: o desafio
  # HTTP-01 exige que a porta 80 do domínio chegue neste servidor pela internet.
  printf '\n%s══════════════════════════════════════════════%s\n' "$YELLOW" "$RESET"
  printf '%s  ANTES de emitir o HTTPS, configure (fora do servidor):%s\n' "$BOLD" "$RESET"
  printf '%s══════════════════════════════════════════════%s\n' "$YELLOW" "$RESET"
  printf '\n%s1) DNS%s: registro A do domínio apontando para seu IP público:\n' "$BOLD" "$RESET"
  printf '     %s%-24s A   %s%s\n' "$CYAN" "$domain" "${pub:-<seu-ip-publico>}" "$RESET"
  printf '\n%s2) Port forwarding no roteador/modem%s → IP interno deste servidor:\n' "$BOLD" "$RESET"
  printf '     %sTCP  80  →  %s:80%s     (validação/renovação do certificado + redirect)\n' "$CYAN" "${lan:-<ip-lan-do-servidor>}" "$RESET"
  printf '     %sTCP 443  →  %s:443%s    (HTTPS do site)\n' "$CYAN" "${lan:-<ip-lan-do-servidor>}" "$RESET"
  printf '\n%sAtenção:%s cada porta externa (80/443) só pode apontar para UM destino.\n' "$YELLOW" "$RESET"
  printf 'Se outro serviço da rede já usa 80/443, remova/ajuste aquela regra ou\n'
  printf 'centralize os sites num único proxy reverso. Não encaminhe 8080 nem RCON.\n\n'
  confirm 'Já configurou o DNS e o port forwarding acima?' || {
    printf '%sConfigure primeiro e rode esta opção novamente.%s\n' "$YELLOW" "$RESET"; pause; return; }

  printf '\n%sVou instalar Nginx + Certbot, criar o proxy reverso e emitir HTTPS.%s\n' "$BOLD" "$RESET"
  confirm 'Continuar?' || { pause; return; }

  # 1) Site precisa estar em 127.0.0.1 (atrás do proxy). Garante a unidade.
  local units="$HOME/.config/systemd/user"
  if [[ ! -e "$units/games-status.service" ]]; then
    STATUS_BIND="127.0.0.1" STATUS_PORT="8080" bash "$SCRIPT_DIR/install_systemd.sh" || {
      printf '%sFalha ao gerar unidades.%s\n' "$RED" "$RESET"; pause; return; }
  fi
  run_sudo loginctl enable-linger "$(whoami)" || true
  systemctl --user enable --now games-status.service || true

  # 2) Instalar nginx + certbot.
  printf '\n%sInstalando pacotes...%s\n' "$DIM" "$RESET"
  run_sudo apt update || true
  run_sudo apt install -y nginx certbot python3-certbot-nginx || {
    printf '%sFalha ao instalar pacotes.%s\n' "$RED" "$RESET"; pause; return; }

  # 3) Gerar a config do Nginx: proxy para 127.0.0.1:8080 e um webroot dedicado
  #    para o desafio ACME (HTTP-01), servido só pela porta 80.
  local conf="/etc/nginx/sites-available/$NGINX_SITE_NAME"
  local webroot="/var/www/$NGINX_SITE_NAME"
  run_sudo mkdir -p "$webroot/.well-known/acme-challenge"
  printf '\n%sCriando %s%s\n' "$DIM" "$conf" "$RESET"
  sudo tee "$conf" >/dev/null <<NGINX
server {
    listen 80;
    server_name $domain;

    # Desafio ACME (HTTP-01) servido diretamente do webroot, sem proxy.
    location /.well-known/acme-challenge/ {
        root $webroot;
    }

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 10s;
    }
}
NGINX
  run_sudo ln -sf "$conf" "/etc/nginx/sites-enabled/$NGINX_SITE_NAME"
  run_sudo nginx -t && run_sudo systemctl reload nginx || {
    printf '%sNginx recusou a configuração; revise %s.%s\n' "$RED" "$conf" "$RESET"; pause; return; }

  # 3b) Checar se o domínio chega neste servidor pela porta 80 (evita certbot cego).
  printf '\n%sVerificando acessibilidade do domínio na porta 80...%s\n' "$DIM" "$RESET"
  local token="acme-precheck-$$"
  echo "$token" | sudo tee "$webroot/.well-known/acme-challenge/$token" >/dev/null || true
  local got=""
  # 'curl -f' sai com código != 0 em erro HTTP/conexão; sob 'set -e' isso encerraria
  # o script. O '|| true' garante que a checagem nunca derrube o menu.
  got="$(curl -fsS -m 10 "http://$domain/.well-known/acme-challenge/$token" 2>/dev/null || true)"
  run_sudo rm -f "$webroot/.well-known/acme-challenge/$token" || true
  if [[ "$got" != "$token" ]]; then
    printf '%s✗ O domínio NÃO respondeu com o conteúdo esperado na porta 80.%s\n' "$RED" "$RESET"
    printf 'Isso significa que a porta 80 externa não chega a este servidor (%s).\n' "${lan:-?}"
    printf 'Causa comum: outra regra de port forwarding usa a porta 80 para outro IP,\n'
    printf 'ou o DNS ainda não propagou. Ajuste e rode a opção novamente.\n'
    printf '%sNão vou chamar o certbot para não gastar tentativas de emissão.%s\n' "$YELLOW" "$RESET"
    pause; return 0
  fi
  printf '%s✔ Porta 80 chega a este servidor. Emitindo certificado...%s\n' "$GREEN" "$RESET"

  # 4) Emitir HTTPS com certbot via webroot (validação só por HTTP-01/porta 80).
  run_sudo certbot certonly --webroot -w "$webroot" -d "$domain" --agree-tos --non-interactive --register-unsafely-without-email \
    && configure_https_block "$conf" "$domain" "$webroot" \
    || { printf '%sCertbot falhou. Veja /var/log/letsencrypt/letsencrypt.log.%s\n' "$YELLOW" "$RESET"; pause; return; }

  printf '\n%s✔ Site publicado com HTTPS.%s\n' "$GREEN" "$RESET"
  printf '  Acesse: %shttps://%s%s\n' "$BOLD" "$domain" "$RESET"
  printf '  A renovação automática é feita pelo timer do certbot (systemd).\n'
  pause
  return
}

# Adiciona o bloco HTTPS (443) ao arquivo do Nginx após o certificado ser emitido,
# mantendo o redirecionamento de 80 para 443.
configure_https_block() {
  local conf="$1" domain="$2" webroot="$3"
  sudo tee "$conf" >/dev/null <<NGINX
server {
    listen 80;
    server_name $domain;

    location /.well-known/acme-challenge/ {
        root $webroot;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name $domain;

    ssl_certificate /etc/letsencrypt/live/$domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$domain/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 10s;
    }
}
NGINX
  run_sudo nginx -t && run_sudo systemctl reload nginx
}

site_services_menu() {
  while true; do
    clear 2>/dev/null || printf '\n'
    printf '%s══════════════════════════════════════════════%s\n' "$CYAN" "$RESET"
    printf '%s  Site e serviços%s\n' "$BOLD" "$RESET"
    printf '%s══════════════════════════════════════════════%s\n' "$CYAN" "$RESET"
    cat <<MENU
    1) Gerar/instalar serviços systemd
    2) Habilitar e iniciar serviços (com linger)
    3) Parar serviços
    4) Desabilitar serviços
    5) Status dos serviços
    6) Ver logs (journalctl)
    7) Testar o site agora (primeiro plano)
    8) ${GREEN}Publicar o site (proxy externo / HTTPS local / LAN)${RESET}
    0) Voltar
MENU
    printf '%s──────────────────────────────────────────────%s\n' "$CYAN" "$RESET"
    read -r -p 'Opção: ' opt || return
    case "$opt" in
      1) svc_install ;;
      2) svc_enable ;;
      3) svc_stop ;;
      4) svc_disable ;;
      5) svc_status ;;
      6) svc_logs ;;
      7) site_test ;;
      8) site_publish ;;
      0) return ;;
      *) printf '%sOpção inválida.%s\n' "$RED" "$RESET"; sleep 1 ;;
    esac
  done
}

main_menu() {
  while true; do
    local data
    data="$(status_json)"
    render_header "$data"
    cat <<MENU
  ${BOLD}Ações${RESET}
    1) Configurar um jogo
    2) Instalar / atualizar
    3) Escolher jogo e iniciar / trocar
    4) Parar e salvar
    5) Status detalhado (JSON)
    6) Abrir console (tmux)
    7) Backup (jogo parado)
    8) ${GREEN}Adicionar novo jogo${RESET}
    9) ${BLUE}Site e serviços${RESET}
    0) Sair
MENU
    printf '%s──────────────────────────────────────────────%s\n' "$CYAN" "$RESET"
    read -r -p "Opção: " choice || exit 0
    case "$choice" in
      1) game_submenu "configurar" configure ;;
      2) game_submenu "instalar/atualizar" install ;;
      3) game_submenu "iniciar/trocar" switch ;;
      4) run_manager stop; pause ;;
      5) "${MANAGER[@]}" status; pause ;;
      6) "${MANAGER[@]}" console || true ;;
      7) game_submenu "backup" backup ;;
      8) add_game_flow ;;
      9) site_services_menu ;;
      0) exit 0 ;;
      *) printf '%sOpção inválida.%s\n' "$RED" "$RESET"; sleep 1 ;;
    esac
  done
}

main_menu
