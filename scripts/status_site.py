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
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Servidores de jogos</title>
<link rel="icon" href="/favicon.ico" sizes="any">
<style>
:root{color-scheme:dark;--bg:#0f1420;--card:#1a2233;--card2:#212c42;--line:#2c3a55;
--text:#e6ecf7;--muted:#95a3bd;--accent:#5b9dff;--ok:#3ddc84;--warn:#ffcb3d;--bad:#ff5d5d;}
*{box-sizing:border-box}
body{margin:0;font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
background:linear-gradient(160deg,#0b0f18,#141b2b);color:var(--text);min-height:100vh}
main{max-width:860px;margin:0 auto;padding:2rem 1.2rem 3rem}
h1{font-size:1.6rem;margin:0 0 .2rem;letter-spacing:.3px}
.sub{color:var(--muted);margin:0 0 1.4rem;font-size:.92rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:.8rem;margin-bottom:1.4rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1rem 1.1rem}
.card .k{color:var(--muted);font-size:.78rem;text-transform:uppercase;letter-spacing:.6px}
.card .v{font-size:1.5rem;font-weight:600;margin-top:.25rem;word-break:break-word}
.pill{display:inline-block;padding:.15em .6em;border-radius:999px;font-size:.82rem;font-weight:600}
.pill.running{background:rgba(61,220,132,.15);color:var(--ok)}
.pill.stopped{background:rgba(149,163,189,.18);color:var(--muted)}
.pill.attention{background:rgba(255,93,93,.15);color:var(--bad)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
border-radius:14px;overflow:hidden}
th,td{text-align:left;padding:.7rem .9rem;border-bottom:1px solid var(--line)}
th{background:var(--card2);color:var(--muted);font-size:.78rem;text-transform:uppercase;letter-spacing:.5px}
tr:last-child td{border-bottom:0}
.tag{font-size:.85rem;font-weight:600}
.tag.on{color:var(--ok)} .tag.pend{color:var(--warn)} .tag.off{color:var(--muted)} .tag.bad{color:var(--bad)}
.dot{display:inline-block;width:.55em;height:.55em;border-radius:50%;margin-right:.4em;vertical-align:middle}
.dot.on{background:var(--ok)} .dot.pend{background:var(--warn)} .dot.off{background:var(--muted)}
.note{color:var(--muted);font-size:.82rem;margin-top:1.2rem}
#time{color:var(--muted);font-size:.8rem;margin-top:.8rem}
.warnbar{background:rgba(255,93,93,.12);border:1px solid rgba(255,93,93,.4);color:var(--bad);
border-radius:10px;padding:.6rem .9rem;margin-bottom:1.2rem;font-size:.9rem;display:none}
</style></head>
<body><main>
<h1>Servidores de jogos</h1>
<p class="sub">Apenas um jogo fica ativo por vez. O estado confirma o processo em execução; a conexão de jogadores depende da inicialização do jogo e da rede.</p>
<div id="warnbar" class="warnbar"></div>
<div class="cards">
  <div class="card"><div class="k">Estado</div><div class="v"><span id="state" class="pill stopped">…</span></div></div>
  <div class="card"><div class="k">Jogo ativo</div><div class="v" id="active">—</div></div>
  <div class="card"><div class="k">Uptime</div><div class="v" id="uptime">—</div></div>
  <div class="card"><div class="k">Jogadores online</div><div class="v" id="players">—</div></div>
</div>
<table><thead><tr><th>Jogo</th><th>Disponibilidade</th></tr></thead><tbody id="games"></tbody></table>
<p class="note">Os jogadores online são exibidos apenas como quantidade agregada. A página é somente leitura: não mostra nomes, endereços, senhas nem permite ações administrativas.</p>
<p id="time"></p>
</main><script src="/status.js"></script></body></html>"""
JAVASCRIPT = """function fmtUptime(s){
  if(s==null) return '—';
  const d=Math.floor(s/86400), h=Math.floor(s%86400/3600), m=Math.floor(s%3600/60);
  const p=[]; if(d) p.push(d+'d'); if(h||d) p.push(h+'h'); p.push(m+'min');
  return p.join(' ');
}
async function refresh(){
  const stateEl=document.getElementById('state');
  try{
    const response=await fetch('/api/status',{cache:'no-store'});
    if(!response.ok) throw new Error('status');
    const data=await response.json();
    const cls=data.state==='attention'?'attention':data.state==='running'?'running':'stopped';
    stateEl.className='pill '+cls;
    stateEl.textContent=data.state==='attention'?'Atenção necessária':
      data.state==='running'?'Em execução':'Parado';
    document.getElementById('active').textContent=data.active_game||'—';
    document.getElementById('uptime').textContent=data.state==='running'?fmtUptime(data.uptime_seconds):'—';
    document.getElementById('players').textContent=
      (data.state==='running'&&data.players_online!=null)?data.players_online:'—';
    const warn=document.getElementById('warnbar');
    if(data.external_processes_detected){
      warn.style.display='block';
      warn.textContent='! Há um servidor rodando fora do gerenciador.';
    } else { warn.style.display='none'; }
    const table=document.getElementById('games'); table.replaceChildren();
    for(const game of data.games.filter(g=>g.configured)){
      const row=document.createElement('tr');
      const nameCell=document.createElement('td'); nameCell.textContent=game.name; row.append(nameCell);
      const availCell=document.createElement('td');
      let text, klass, dot;
      if(!game.enabled){text='Desabilitado';klass='off';dot='off';}
      else if(!game.installed){text='Instalação pendente';klass='pend';dot='pend';}
      else if(game.experimental){text='Validação pendente';klass='pend';dot='pend';}
      else if(game.id===data.active_game){text='Processo ativo';klass='on';dot='on';}
      else {text='Instalado';klass='on';dot='off';}
      availCell.innerHTML='<span class="dot '+dot+'"></span>';
      const label=document.createElement('span'); label.className='tag '+klass; label.textContent=text;
      availCell.append(label); row.append(availCell); table.append(row);
    }
    document.getElementById('time').textContent='Consultado em '+new Date(data.checked_at*1000).toLocaleString();
  }catch(_){
    stateEl.className='pill attention'; stateEl.textContent='Indisponível';
    document.getElementById('active').textContent='—';
    document.getElementById('uptime').textContent='—';
    document.getElementById('players').textContent='—';
    document.getElementById('games').replaceChildren();
    document.getElementById('time').textContent='Não foi possível consultar o servidor.';
  }
}
refresh(); setInterval(refresh, 10000);
"""

# Ícone do site (joystick + servidor), gerado por scripts/make_favicon.py e
# versionado ao lado deste arquivo. Carregado uma vez no import; se ausente, a rota
# /favicon.ico responde 404 sem derrubar o site.
try:
    FAVICON = (Path(__file__).with_name("favicon.ico")).read_bytes()
except OSError:
    FAVICON = None


def handler(manager):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = self.path.split("?", 1)[0]
            if route == "/favicon.ico":
                # Ícone estático: pode ser cacheado (ao contrário do conteúdo dinâmico).
                if FAVICON is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/x-icon")
                self.send_header("Content-Length", str(len(FAVICON)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(FAVICON)
                return
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
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "script-src 'self'; frame-ancestors 'none'")
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
