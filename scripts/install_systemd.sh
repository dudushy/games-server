#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
GAMES_ROOT="${GAMES_ROOT:-$HOME/.local/share/games-server}"
export GAMES_ROOT
# Endereço/porta do site de consulta. Padrão seguro em loopback (use um proxy
# reverso HTTPS na frente). Para expor direto, defina STATUS_BIND=0.0.0.0.
STATUS_BIND="${STATUS_BIND:-127.0.0.1}"
STATUS_PORT="${STATUS_PORT:-8080}"
export STATUS_BIND STATUS_PORT
python3 - "$SCRIPT_DIR" <<'PY'
import os
from pathlib import Path
import sys

scripts = Path(sys.argv[1])
root = Path(os.environ['GAMES_ROOT']).expanduser().absolute()
status_bind = os.environ['STATUS_BIND']
status_port = os.environ['STATUS_PORT']
units = Path.home() / '.config/systemd/user'
units.mkdir(parents=True, exist_ok=True)
def quoted(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'
def write(name, body):
    path = units / name
    if path.exists():
        raise SystemExit(f'Unidade existente preservada: {path}; revise manualmente.')
    path.write_text(body)
    print(path)
for name in ('games-server.service', 'games-status.service'):
    if (units / name).exists():
        raise SystemExit(f'Unidade existente preservada: {units / name}')
write('games-server.service', f'''[Unit]
Description=Supervisão do servidor de jogos
After=network-online.target

[Service]
Type=simple
UMask=0077
ExecStart=/usr/bin/python3 {quoted(scripts / 'manager.py')} --root {quoted(root)} supervise
ExecStop=/usr/bin/python3 {quoted(scripts / 'manager.py')} --root {quoted(root)} service-stop
Restart=on-failure
RestartSec=30
TimeoutStopSec=infinity
KillMode=process
SendSIGKILL=no

[Install]
WantedBy=default.target
''')
write('games-status.service', f'''[Unit]
Description=Consulta pública dos servidores de jogos

[Service]
Type=simple
UMask=0077
ExecStart=/usr/bin/python3 {quoted(scripts / 'status_site.py')} --root {quoted(root)} --bind {quoted(status_bind)} --port {quoted(status_port)}
Restart=on-failure
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=default.target
''')
PY
systemctl --user daemon-reload
printf '\nUnidades criadas, ainda desabilitadas. Para habilitar, siga docs/operacao.md.\n'
