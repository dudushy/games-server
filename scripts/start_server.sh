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
      0) exit 0 ;;
      *) printf '%sOpção inválida.%s\n' "$RED" "$RESET"; sleep 1 ;;
    esac
  done
}

main_menu
