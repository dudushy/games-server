#!/usr/bin/env python3
"""Gerenciador local de um servidor por vez, com tmux e dados persistentes."""
import argparse
import contextlib
import fcntl
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time

from catalog import GAMES, catalog, defaults, launch, persistent_links, validate_custom_entry, CUSTOM_FILE, BUILTIN
from providers import fetch, java_major
from rcon import source_commands, web_commands

SCRIPT = Path(__file__).resolve()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + secrets.token_hex(6))
    try:
        with temporary.open("x") as output:
            json.dump(value, output, indent=2, ensure_ascii=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def proc_info(pid):
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        fields = raw[raw.rfind(")") + 2:].split()
        return {"pid": int(pid), "state": fields[0], "pgid": int(fields[2]),
                "sid": int(fields[3]), "start": fields[19]}
    except (OSError, ValueError, IndexError):
        return None


def processes():
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            info = proc_info(entry.name)
            if info and info["state"] != "Z":
                yield info


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def living(run):
    if not run or run.get("boot") != boot_id():
        return False
    leader = proc_info(run["pid"])
    if leader and leader["start"] != run["start"]:
        return False
    # O grupo pode continuar vivo depois que o processo principal sair.
    return any(p["pgid"] == run["pid"] and p["sid"] == run["pid"] for p in processes())


class Manager:
    def __init__(self, root):
        self.root = Path(root).expanduser().absolute()
        self.runtime = self.root / "runtime"
        self.socket = self.runtime / "tmux.sock"
        if len(str(self.socket).encode()) > 100:
            raise ValueError("GAMES_ROOT muito longo para o socket tmux; use um caminho menor")

    @property
    def games(self):
        # Catálogo mesclado (embutidos + custom), relido a cada acesso para refletir
        # jogos recém-adicionados sem recriar o gerenciador.
        return catalog(self.root)

    def initialize(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        for name in ("config", "games", "backups", "runtime", "tools"):
            (self.root / name).mkdir(exist_ok=True)

    @contextlib.contextmanager
    def lock(self, wait=False):
        self.initialize()
        with (self.runtime / "manager.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
            except BlockingIOError:
                raise ValueError("Outra operação está em andamento; aguarde") from None
            yield

    def config(self, game):
        cfg = read_json(self.root / "config" / f"{game}.json")
        if cfg is None:
            raise ValueError(f"Configure primeiro: ./start_server.sh configure {game}")
        return cfg

    def paths(self, game):
        base = self.root / "games" / game
        return base, base / "current", base / "data"

    def run_state(self):
        return read_json(self.runtime / "run.json")

    def desired(self, game):
        atomic_json(self.runtime / "desired.json", {"game": game})

    def tmux(self, *args, check=True):
        return subprocess.run(["tmux", "-S", str(self.socket), *args],
                              capture_output=True, text=True, check=check)

    def external(self):
        run = self.run_state()
        managed_group = run["pid"] if living(run) else None
        needles = ("valheim_server", "ConanSandboxServer", "RustDedicated", "SMALLANDServer", "HytaleServer.jar")
        found = []
        for proc in processes():
            if proc["pgid"] == managed_group:
                continue
            try:
                args = Path(f'/proc/{proc["pid"]}/cmdline').read_bytes().decode(errors="replace").split("\0")
                executable = Path(args[0]).name
                matched = any(executable.startswith(n) for n in needles[:4])
                if "java" in executable:
                    matched = matched or any("HytaleServer.jar" in a or a.endswith("server.jar") for a in args)
                if matched:
                    found.append(proc["pid"])
            except (OSError, IndexError):
                continue
        return found

    def assert_no_external(self):
        if found := self.external():
            raise ValueError(f"Servidor fora do gerenciador detectado (PIDs {found}). Veja docs/migracao.md")

    def configure(self, game):
        games = self.games
        if game not in games:
            raise ValueError(f"Jogo desconhecido: {game}. Cadastre com add-game ou use um embutido.")
        path = self.root / "config" / f"{game}.json"
        if path.exists():
            print(f"Configuração preservada. Edite com o jogo parado: {path}")
            return
        meta = games[game]
        cfg = defaults(game, games)
        if sys.stdin.isatty():
            cfg["enabled"] = input("Habilitar este jogo? [s/N]: ").strip().lower() == "s"
            if game == "valheim":
                cfg["server_name"] = input("Nome público [Meu Servidor]: ").strip() or "Meu Servidor"
                cfg["world"] = input("Mundo [Dedicated]: ").strip() or "Dedicated"
                cfg["password"] = getpass.getpass("Senha do jogo (mínimo 5 caracteres): ")
            elif game in ("conan", "rust"):
                cfg["rcon_password"] = getpass.getpass("Senha RCON local (mínimo 12 caracteres): ")
            elif game == "minecraft":
                print("Leia https://www.minecraft.net/eula antes de aceitar.")
                cfg["eula_accepted"] = input("Você aceita a EULA? [s/N]: ").strip().lower() == "s"
            elif game == "hytale":
                cfg["downloader"] = input("Caminho absoluto do Hytale Downloader oficial: ").strip()
            elif meta.get("custom"):
                # Perguntas genéricas conforme o provedor e o modo de parada do jogo custom.
                if meta["provider"] == "mojang":
                    print("Leia https://www.minecraft.net/eula antes de aceitar.")
                    cfg["eula_accepted"] = input("Você aceita a EULA? [s/N]: ").strip().lower() == "s"
                elif meta["provider"] == "hytale":
                    cfg["downloader"] = input("Caminho absoluto do Downloader oficial: ").strip()
                if meta["stop"] in ("source", "web"):
                    cfg["rcon_password"] = getpass.getpass("Senha RCON local (mínimo 12 caracteres): ")
        atomic_json(path, cfg)
        print(f"Configuração criada: {path}\nRevise antes de instalar/iniciar.")

    def add_game(self, game_id=None):
        """Cadastra um jogo custom em config/custom_games.json (interativo)."""
        if not sys.stdin.isatty():
            raise ValueError("add-game exige um terminal interativo")
        custom_path = self.root / "config" / CUSTOM_FILE
        current = read_json(custom_path, {}) or {}
        game_id = (game_id or input("Identificador (ex.: palworld): ").strip()).lower()
        if game_id in BUILTIN:
            raise ValueError("id reservado por um jogo embutido")
        if game_id in current:
            raise ValueError(f"Já existe um jogo custom com id {game_id}; edite {custom_path}")
        name = input("Nome de exibição: ").strip()
        print("Provedores: steam (SteamCMD), mojang (JAR Minecraft), hytale (downloader)")
        provider = input("Provider [steam]: ").strip() or "steam"
        entry = {"name": name, "provider": provider}
        if provider == "steam":
            entry["appid"] = input("App ID do servidor dedicado (SteamCMD): ").strip()
        entry["executable"] = input("Caminho relativo do executável dentro da release: ").strip()
        print("Modos de parada: sigint | console (tmux) | source (RCON) | web (WebRCON) | hook")
        entry["stop"] = input("Modo de parada [console]: ").strip() or "console"
        port_raw = input("Porta principal: ").strip()
        try:
            entry["port"] = int(port_raw)
        except ValueError:
            raise ValueError("Porta deve ser um número inteiro") from None
        persistent = {}
        print("Links de persistência (Enter vazio para terminar). Origem relativa → destino em data/.")
        while True:
            relative = input("  Caminho na release (vazio p/ terminar): ").strip()
            if not relative:
                break
            destination = input("  Destino em data/: ").strip()
            persistent[relative] = destination
        if persistent:
            entry["persistent"] = persistent
        # Valida antes de gravar; levanta ValueError com a causa.
        validate_custom_entry(game_id, entry)
        current[game_id] = entry
        atomic_json(custom_path, current)
        print(f"Jogo custom cadastrado: {game_id} em {custom_path}")
        print(f"Agora configure: ./start_server.sh configure {game_id}")

    def validate_config(self, game, cfg, for_start=False):
        games = self.games
        if game not in games:
            raise ValueError(f"Jogo desconhecido: {game}")
        meta = games[game]
        if not cfg.get("enabled"):
            raise ValueError(f"Jogo desabilitado: config/{game}.json → enabled=true")
        for key in ("port", "query_port", "rcon_port"):
            if key in cfg and (type(cfg[key]) is not int or not 1 <= cfg[key] <= 65535):
                raise ValueError(f"Porta inválida: {key}")
        for key in ("start_timeout", "stop_timeout"):
            if type(cfg.get(key)) is not int or not 1 <= cfg[key] <= 3600:
                raise ValueError(f"{key} deve estar entre 1 e 3600 segundos")
        if not isinstance(cfg.get("extra_args"), list) or not all(isinstance(x, str) for x in cfg["extra_args"]):
            raise ValueError("extra_args deve ser uma lista de strings")
        needs_java = game in ("minecraft", "hytale") or (meta.get("custom") and meta["provider"] in ("mojang", "hytale"))
        needs_eula = game == "minecraft" or (meta.get("custom") and meta["provider"] == "mojang")
        if needs_eula and not cfg.get("eula_accepted"):
            raise ValueError("É necessário aceitar a EULA explicitamente (eula_accepted=true)")
        if needs_java and not re.fullmatch(r"[1-9][0-9]*[MG]", cfg.get("heap", "")):
            raise ValueError("heap inválido; exemplo: 4G")
        if meta.get("custom") and not isinstance(cfg.get("launch_args"), list):
            raise ValueError("launch_args deve ser uma lista de strings")
        if not for_start:
            return
        if game == "valheim" and len(cfg.get("password", "")) < 5:
            raise ValueError("Configure uma senha do Valheim com pelo menos 5 caracteres")
        uses_rcon = game in ("conan", "rust") or (meta.get("custom") and meta["stop"] in ("source", "web"))
        uses_web = game == "rust" or (meta.get("custom") and meta["stop"] == "web")
        if uses_rcon:
            password = cfg.get("rcon_password", "")
            if len(password) < 12 or any(c in password for c in '\n\r"\\'):
                raise ValueError("Senha RCON: mínimo 12 caracteres, sem aspas, barra invertida ou quebras de linha")
        if uses_web:
            try:
                import websocket  # noqa: F401
            except ImportError:
                raise ValueError("Instale python3-websocket para controlar servidores via WebRCON") from None
        uses_hook = game == "smalland" or (meta.get("custom") and meta["stop"] == "hook")
        if uses_hook:
            hook = Path(cfg.get("stop_hook", ""))
            if not cfg.get("shutdown_verified") or not hook.is_absolute() or not os.access(hook, os.X_OK):
                raise ValueError("Encerramento por hook pendente de validação: configure stop_hook e shutdown_verified; docs/jogos.md")
            if not cfg.get("launch_args") or not all(isinstance(x, str) for x in cfg["launch_args"]):
                raise ValueError("Este jogo exige launch_args revisados a partir do pacote instalado")

    def backup(self, game):
        run = self.run_state()
        if living(run) and run["game"] == game:
            raise ValueError("Backup exige o jogo parado para obter um snapshot consistente")
        self.assert_no_external()
        _, current, data = self.paths(game)
        folder = self.root / "backups" / game
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secrets.token_hex(4) + ".tar.gz")
        with tarfile.open(str(target) + ".partial", "w:gz", dereference=False) as archive:
            if data.exists():
                # Recusa symlinks: um backup não deve silenciosamente omitir mundos externos.
                if any(p.is_symlink() for p in data.rglob("*")):
                    raise ValueError("data/ contém links simbólicos; copie os dados reais antes do backup")
                archive.add(data, arcname="data")
            archive.add(self.root / "config" / f"{game}.json", arcname="config.json")
            if (current / "release.json").is_file():
                archive.add(current / "release.json", arcname="release.json")
        Path(str(target) + ".partial").replace(target)
        print(f"Backup: {target}")
        return target

    def import_data(self, game, source):
        if game not in ("valheim", "conan"):
            raise ValueError("Importação assistida disponível somente para Valheim e Conan")
        self.config(game)
        self.assert_no_external()
        run = self.run_state()
        if living(run) and run["game"] == game:
            raise ValueError("Pare o jogo antes de importar dados")
        source = Path(source).expanduser().resolve()
        base, _, data = self.paths(game)
        if not source.is_dir() or source == Path("/") or source == self.root or source in data.parents or data in source.parents:
            raise ValueError("Diretório de origem inválido")
        if data.exists() and any(p.is_file() or p.is_symlink() for p in data.rglob("*")):
            raise ValueError("data/ já contém arquivos; importação recusada para não sobrescrever um mundo")
        base.mkdir(parents=True, exist_ok=True)
        stage = base / ("import-" + secrets.token_hex(8))
        stage.mkdir()
        sources = {source: stage} if game == "valheim" else {source / "ConanSandbox/Saved": stage / "Saved"}
        if game == "conan" and (source / "ConanSandbox/Mods").exists():
            sources[source / "ConanSandbox/Mods"] = stage / "Mods"
        for origin, destination in sources.items():
            if not origin.is_dir() or origin.is_symlink() or any(p.is_symlink() for p in origin.rglob("*")):
                raise ValueError("Origem ausente ou com links simbólicos; revise a cópia manualmente")
            shutil.copytree(origin, destination, dirs_exist_ok=True)
        if data.exists():
            data.rename(base / ("data-before-import-" + secrets.token_hex(8)))
        stage.rename(data)
        self.backup(game)
        print("Dados importados por cópia; origem preservada. Revise as configurações antes de iniciar.")

    def install(self, game):
        games = self.games
        meta = games[game]
        cfg = self.config(game)
        self.validate_config(game, cfg)
        self.assert_no_external()
        run = self.run_state()
        if living(run) and run["game"] == game:
            raise ValueError("Pare este jogo antes de atualizar: ./start_server.sh stop")
        base, current, data = self.paths(game)
        data.mkdir(parents=True, exist_ok=True)
        self.backup(game)
        releases = base / "releases"
        releases.mkdir(exist_ok=True)
        stage = releases / ("download-" + secrets.token_hex(8))
        stage.mkdir()
        print("Baixando em uma pasta isolada; a versão atual será preservada se houver falha.", flush=True)
        metadata = fetch(game, cfg, stage, self.root / "tools" / game, meta)
        executable = stage / meta["executable"]
        if not executable.is_file() or executable.stat().st_size == 0:
            raise ValueError(f"Executável esperado ausente: {meta['executable']}")
        if meta["provider"] == "steam" and not os.access(executable, os.X_OK):
            raise ValueError("Executável baixado não tem permissão de execução")
        for relative, persistent in persistent_links(game, games).items():
            destination = data / persistent
            destination.mkdir(parents=True, exist_ok=True)
            link = stage / relative
            if link.is_symlink():
                raise ValueError("Link inesperado no download")
            if link.exists():
                # Defaults baixados ficam na release para consulta, sem entrar em data/.
                link.rename(link.with_name(link.name + ".vendor-defaults"))
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(destination, target_is_directory=True)
        metadata["installed_at"] = time.time()
        atomic_json(stage / "release.json", metadata)
        release = stage.with_name(stage.name.replace("download-", "release-"))
        stage.rename(release)
        next_link = base / "current.next"
        next_link.unlink(missing_ok=True)
        next_link.symlink_to(release, target_is_directory=True)
        next_link.replace(current)
        print(f"Versão instalada: {release}\nDados e configurações preservados. O jogo não foi iniciado.")

    def prepare_data(self, game, cfg):
        _, _, data = self.paths(game)
        data.mkdir(parents=True, exist_ok=True)
        if game == "conan":
            path = data / "Saved/Config/LinuxServer/Game.ini"
            path.parent.mkdir(parents=True, exist_ok=True)
            text = path.read_text() if path.exists() else ""
            # Altera apenas as chaves RCON, preservando as demais seções e comentários.
            values = {"RconEnabled": "1", "RconPort": str(cfg["rcon_port"]), "RconPassword": cfg["rcon_password"]}
            lines, section = [], ""
            for line in text.splitlines():
                if line.strip().startswith("["):
                    section = line.strip().lower()
                if section == "[rconplugin]" and line.split("=", 1)[0].strip().lower() in {k.lower() for k in values}:
                    continue
                lines.append(line)
            lines += ["", "[RconPlugin]"] + [f"{k}={v}" for k, v in values.items()]
            path.write_text("\n".join(lines) + "\n")
        elif game == "rust":
            path = data / "server/main/cfg/server.cfg"
            path.parent.mkdir(parents=True, exist_ok=True)
            text = path.read_text() if path.exists() else f'server.maxplayers {cfg["max_players"]}\n'
            controlled = {"rcon.web": "1", "rcon.ip": '"127.0.0.1"',
                          "rcon.port": str(cfg["rcon_port"]), "rcon.password": f'"{cfg["rcon_password"]}"'}
            lines = [line for line in text.splitlines() if not line.split() or line.split()[0] not in controlled]
            path.write_text("\n".join(lines + [f"{k} {v}" for k, v in controlled.items()]) + "\n")
        elif game == "minecraft":
            (data / "eula.txt").write_text("eula=true\n")
            properties = data / "server.properties"
            if not properties.exists():
                properties.write_text(f'server-port={cfg["port"]}\nonline-mode=true\nlevel-name=world\n')
        elif self.games[game].get("custom") and self.games[game]["provider"] == "mojang":
            # Jogos custom baseados em JAR Mojang também exigem a EULA aceita em disco.
            (data / "eula.txt").write_text("eula=true\n")

    def preflight(self, game):
        games = self.games
        meta = games[game]
        cfg = self.config(game)
        self.validate_config(game, cfg, for_start=True)
        _, current, data = self.paths(game)
        if not (current / meta["executable"]).is_file():
            raise ValueError(f"Instale antes de iniciar: ./start_server.sh install {game}")
        needs_java = game in ("minecraft", "hytale") or (meta.get("custom") and meta["provider"] in ("mojang", "hytale"))
        if needs_java:
            metadata = read_json(current / "release.json", {})
            required = metadata.get("java_major", 25)
            if java_major(cfg["java"]) < required:
                raise ValueError(f"Java {required} ou superior necessário")
        if not shutil.which("tmux"):
            raise ValueError("Instale tmux")
        return cfg

    def start(self, game):
        cfg = self.preflight(game)
        self.assert_no_external()
        if living(self.run_state()):
            raise ValueError("Já existe um jogo em execução; use switch")
        self.prepare_data(game, cfg)
        token = secrets.token_hex(16)
        # Snapshot privado: alterações posteriores no JSON não mudam como parar o processo atual.
        snapshot = self.runtime / f"{token}.config.json"
        atomic_json(snapshot, cfg)
        self.tmux("kill-session", "-t", "game", check=False)
        command = shlex.join([sys.executable, str(SCRIPT), "--root", str(self.root), "_run", game, token])
        self.tmux("new-session", "-d", "-s", "game", "exec " + command)
        self.desired(game)
        deadline = time.monotonic() + cfg["start_timeout"]
        while time.monotonic() < deadline:
            run = self.run_state()
            if run and run.get("token") == token and living(run):
                time.sleep(1)
                if not living(run):
                    break
                print(f"Processo de {game} iniciado. Confirme no console quando estiver pronto para jogadores.")
                return
            if (self.runtime / f"{token}.exit.json").exists():
                break
            time.sleep(0.2)
        self.desired(None)
        atomic_json(self.runtime / "blocked.json", {"reason": "startup", "game": game})
        raise ValueError("Inicialização não confirmada. Veja console/logs; reinício automático bloqueado até uma ação manual")

    def stop(self, preserve_desired=False):
        if not preserve_desired:
            self.desired(None)
        run = self.run_state()
        if not living(run):
            if preserve_desired:
                atomic_json(self.runtime / "blocked.json", {"reason": "service-stopped"})
            print("Nenhum processo gerenciado ativo.")
            return
        cfg = read_json(self.runtime / f'{run["token"]}.config.json')
        game = run["game"]
        atomic_json(self.runtime / "blocked.json", {"reason": "stopping", "game": game})
        mode = self.games[game]["stop"]
        print(f"Solicitando encerramento de {game}; aguardando até {cfg['stop_timeout']}s...", flush=True)
        if mode == "sigint":
            os.killpg(run["pid"], signal.SIGINT)
        elif mode == "console":
            commands = ["save-all flush", "stop"] if game == "minecraft" else ["stop"]
            for command in commands:
                self.tmux("send-keys", "-t", "game:0.0", "-l", command)
                self.tmux("send-keys", "-t", "game:0.0", "Enter")
        elif mode == "source":
            source_commands(cfg["rcon_port"], cfg["rcon_password"], ["shutdown"])
        elif mode == "web":
            web_commands(cfg["rcon_port"], cfg["rcon_password"], ["server.save", "quit"])
        else:
            env = os.environ.copy()
            env.update(GAME_PID=str(run["pid"]), GAME_DATA=str(self.paths(game)[2]))
            subprocess.run([cfg["stop_hook"]], env=env, check=True, timeout=cfg["stop_timeout"])
        deadline = time.monotonic() + cfg["stop_timeout"]
        while time.monotonic() < deadline:
            result = read_json(self.runtime / f'{run["token"]}.exit.json')
            if not living(run) and result:
                allowed = [0, 130, -signal.SIGINT] if mode == "sigint" else [0]
                if result.get("code") not in allowed:
                    raise ValueError("Processo terminou com erro; troca bloqueada. Inspecione os logs e os dados")
                self.backup(game)
                if preserve_desired:
                    atomic_json(self.runtime / "blocked.json", {"reason": "service-stopped"})
                else:
                    (self.runtime / "blocked.json").unlink(missing_ok=True)
                print("Processo encerrado e backup concluído.")
                return
            time.sleep(0.25)
        raise ValueError("Encerramento não confirmado. Nenhum processo foi forçado; troca e reinício automático bloqueados")

    def switch(self, game):
        self.preflight(game)
        self.assert_no_external()
        run = self.run_state()
        if living(run) and run["game"] == game:
            print("Este jogo já está em execução.")
            return
        self.stop()
        (self.runtime / "blocked.json").unlink(missing_ok=True)
        self.start(game)

    def status(self):
        games = self.games
        run = self.run_state()
        alive = living(run)
        blocked = read_json(self.runtime / "blocked.json")
        return {"checked_at": time.time(), "active_game": run["game"] if alive else None,
                "state": "attention" if blocked else "running" if alive else "stopped",
                "availability": "process_only", "external_processes_detected": bool(self.external()),
                "games": [{"id": game, "name": meta["name"],
                           "configured": (self.root / "config" / f"{game}.json").is_file(),
                           "enabled": bool(read_json(self.root / "config" / f"{game}.json", {}).get("enabled")),
                           "installed": (self.paths(game)[1] / meta["executable"]).is_file(),
                           "experimental": game == "smalland"} for game, meta in games.items()]}

    def resume(self):
        if living(self.run_state()) or (self.runtime / "blocked.json").exists():
            return
        desired = read_json(self.runtime / "desired.json", {}).get("game")
        if desired:
            self.start(desired)


def run_game(manager, game, token):
    cfg = read_json(manager.runtime / f"{token}.config.json")
    _, current, data = manager.paths(game)
    args, cwd, env = launch(game, cfg, current.resolve(), data, manager.games)
    # O processo tem grupo próprio; SIGINT nunca alcança outro jogo ou o gerenciador.
    logs = manager.paths(game)[0] / "logs"
    logs.mkdir(exist_ok=True)
    log = (logs / f"{token}.log").open("ab", buffering=0)
    # Sinais interativos entregues ao painel tmux (Ctrl+C, Ctrl+Z, Ctrl+\) atingiriam
    # este runner, que fica em primeiro plano no painel. Se ele morresse, o estado
    # ficaria inconsistente (jogo vivo, sem monitor). O filho é iniciado em nova
    # sessão e reaplica o comportamento padrão desses sinais via preexec_fn, para que
    # apenas o jogo os receba se algum dia for endereçado ao seu próprio grupo.
    interactive_signals = (signal.SIGINT, signal.SIGTSTP, signal.SIGQUIT)

    def reset_child_signals():
        for sig in interactive_signals:
            signal.signal(sig, signal.SIG_DFL)

    child = subprocess.Popen(args, cwd=cwd, env=env, start_new_session=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             preexec_fn=reset_child_signals)
    # Agora que o filho já foi criado (e restaurou os padrões), o runner passa a
    # ignorar esses sinais: Ctrl+C no console anexado não derruba o monitoramento.
    for sig in interactive_signals:
        signal.signal(sig, signal.SIG_IGN)
    def copy_output():
        while chunk := child.stdout.read1(65536):
            log.write(chunk)
            try:
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
            except OSError:
                pass
    output_thread = threading.Thread(target=copy_output, daemon=True)
    output_thread.start()
    info = proc_info(child.pid)
    if info is None:
        atomic_json(manager.runtime / f"{token}.exit.json", {"code": child.wait()})
        return
    run = {"game": game, "token": token, "pid": child.pid, "start": info["start"], "boot": boot_id()}
    atomic_json(manager.runtime / "run.json", run)
    code = child.wait()
    while living(run):
        time.sleep(0.25)
    output_thread.join(timeout=2)
    atomic_json(manager.runtime / f"{token}.exit.json", {"code": code, "finished_at": time.time()})
    print(f"\nProcesso encerrado (código {code}).", flush=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("GAMES_ROOT", str(Path.home() / ".local/share/games-server")))
    parser.add_argument("action", choices=["configure", "install", "update", "start", "switch", "stop",
                                           "backup", "import-data", "status", "console", "resume", "supervise",
                                           "_run", "service-stop", "add-game"])
    parser.add_argument("game", nargs="?")
    parser.add_argument("token", nargs="?")
    args = parser.parse_args()
    manager = Manager(args.root)
    # Ações que operam sobre um jogo existente devem receber um id conhecido no catálogo.
    game_actions = ("configure", "install", "update", "start", "switch", "backup", "import-data", "_run")
    if args.action in game_actions and args.game and args.game not in manager.games:
        raise ValueError(f"Jogo desconhecido: {args.game}. Use status para listar ou add-game para cadastrar.")
    if args.action == "_run":
        run_game(manager, args.game, args.token)
        return
    if args.action == "status":
        print(json.dumps(manager.status(), indent=2, ensure_ascii=False))
        return
    if args.action == "console":
        os.execvp("tmux", ["tmux", "-S", str(manager.socket), "attach-session", "-t", "game"])
    if args.action == "supervise":
        with manager.lock():
            if read_json(manager.runtime / "blocked.json", {}).get("reason") == "service-stopped":
                (manager.runtime / "blocked.json").unlink(missing_ok=True)
        while True:
            try:
                with manager.lock():
                    manager.resume()
            except Exception as error:
                print(f"Supervisão: {error}", file=sys.stderr, flush=True)
            time.sleep(30)
    with manager.lock(wait=args.action == "service-stop"):
        if args.action in ("configure", "install", "update", "start", "switch", "backup", "import-data") and not args.game:
            raise ValueError("Informe o jogo")
        if args.action == "add-game":
            manager.add_game(args.game)
        elif args.action == "configure":
            manager.configure(args.game)
        elif args.action in ("install", "update"):
            manager.install(args.game)
        elif args.action == "start":
            manager.preflight(args.game)
            if living(manager.run_state()):
                raise ValueError("Há um jogo ativo; use switch")
            (manager.runtime / "blocked.json").unlink(missing_ok=True)
            manager.start(args.game)
        elif args.action == "switch":
            manager.switch(args.game)
        elif args.action in ("stop", "service-stop"):
            manager.stop(preserve_desired=args.action == "service-stop")
        elif args.action == "backup":
            manager.backup(args.game)
        elif args.action == "import-data":
            if not args.token:
                raise ValueError("Informe a pasta de origem após o jogo")
            manager.import_data(args.game, args.token)
        elif args.action == "resume":
            manager.resume()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Operação interrompida. Confira o status antes de continuar.", file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        print(f"Erro: {error}", file=sys.stderr)
        sys.exit(1)
