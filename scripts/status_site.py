#!/usr/bin/env python3
"""Página de consulta: somente GET, sem console, configurações ou arquivos privados."""
import argparse
import errno
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys

from manager import Manager

PAGE = """<!doctype html>
<html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Servidores de jogos</title>
<main><h1>Servidores de jogos</h1><p id="state" role="status">Consultando…</p>
<p>Apenas um jogo fica ativo por vez. A indicação confirma o processo em execução;
a conexão de jogadores depende da inicialização do jogo e da rede.</p>
<table><thead><tr><th>Jogo</th><th>Disponibilidade</th></tr></thead><tbody id="games"></tbody></table>
<p id="time"></p></main><script src="/status.js"></script></html>"""
JAVASCRIPT = """async function refresh() {
  try {
    const response = await fetch('/api/status', {cache: 'no-store'});
    if (!response.ok) throw new Error('status');
    const data = await response.json();
    document.getElementById('state').textContent =
      data.state === 'attention' ? 'O administrador precisa verificar o servidor.' :
      data.active_game ? 'Processo ativo: ' + data.active_game : 'Nenhum jogo gerenciado ativo.';
    if (data.external_processes_detected)
      document.getElementById('state').textContent += ' Há um servidor fora do gerenciador.';
    const table = document.getElementById('games'); table.replaceChildren();
    for (const game of data.games.filter(game => game.configured)) {
      const row = document.createElement('tr');
      for (const value of [game.name, !game.enabled ? 'Desabilitado' :
        !game.installed ? 'Instalação pendente' : game.experimental ? 'Validação pendente' :
        game.id === data.active_game ? 'Processo ativo' : 'Instalado']) {
        const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
      }
      table.append(row);
    }
    document.getElementById('time').textContent = 'Consultado em ' + new Date(data.checked_at * 1000).toLocaleString();
  } catch (_) {
    document.getElementById('state').textContent = 'Não foi possível consultar o servidor.';
    document.getElementById('games').replaceChildren();
    document.getElementById('time').textContent = '';
  }
}
refresh(); setInterval(refresh, 10000);
"""


def handler(manager):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = self.path.split("?", 1)[0]
            if route == "/":
                body, kind = PAGE.encode(), "text/html; charset=utf-8"
            elif route == "/status.js":
                body, kind = JAVASCRIPT.encode(), "text/javascript; charset=utf-8"
            elif route == "/api/status":
                try:
                    body = json.dumps(manager.status()).encode()
                except Exception:
                    self.send_error(503, "Status unavailable")
                    return
                kind = "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass
    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("GAMES_ROOT", str(Path.home() / ".local/share/games-server")))
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer((args.bind, args.port), handler(Manager(args.root)))
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            print(f"Porta {args.port} já está em uso em {args.bind}. "
                  "O serviço games-status provavelmente já está ativo "
                  "(use 'Status dos serviços') ou escolha outra porta.", file=sys.stderr)
            sys.exit(1)
        raise
    print(f"Site: http://{args.bind}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSite encerrado.", flush=True)
