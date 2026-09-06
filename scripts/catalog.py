"""Adaptadores: comandos explícitos, sem executar conteúdo obtido da internet.

O catálogo tem uma parte embutida (jogos validados com argumentos próprios) e uma
parte custom, carregada de ``config/custom_games.json``. Jogos custom reutilizam o
perfil genérico do provedor (SteamCMD, Mojang ou Hytale) e definem seus próprios
argumentos de inicialização em ``launch_args``; não recebem argumentos especiais no
código, justamente para permitir adicionar qualquer servidor dedicado sem editar
este arquivo.
"""
import json
import os
from pathlib import Path
import re

# Provedores suportados para jogos custom.
PROVIDERS = ("steam", "mojang", "hytale")
# Modos de encerramento aceitos ao cadastrar um jogo custom.
STOP_MODES = ("sigint", "console", "source", "web", "hook")

GAMES = {
    "valheim": {"name": "Valheim", "provider": "steam", "appid": "896660",
                "executable": "valheim_server.x86_64", "stop": "sigint", "port": 2456},
    "conan": {"name": "Conan Exiles Enhanced", "provider": "steam", "appid": "443030",
              "executable": "ConanSandbox/Binaries/Linux/ConanSandboxServer-Linux-Shipping",
              "stop": "source", "port": 7777},
    "rust": {"name": "Rust", "provider": "steam", "appid": "258550",
             "executable": "RustDedicated", "stop": "web", "port": 28015},
    "minecraft": {"name": "Minecraft Java (vanilla)", "provider": "mojang",
                  "executable": "server.jar", "stop": "console", "port": 25565},
    "hytale": {"name": "Hytale", "provider": "hytale", "executable": "Server/HytaleServer.jar",
               "stop": "console", "port": 5520},
    "smalland": {"name": "Smalland (experimental)", "provider": "steam", "appid": "808040",
                 "executable": "SMALLAND/Binaries/Linux/SMALLANDServer-Linux-Shipping",
                 "stop": "hook", "port": 7777},
}

# IDs embutidos com adaptadores próprios de argumentos; nunca podem ser sobrescritos.
BUILTIN = frozenset(GAMES)

CUSTOM_FILE = "custom_games.json"

VALID_ID = re.compile(r"[a-z][a-z0-9_-]{1,31}$")


def validate_custom_entry(game_id, entry):
    """Valida uma entrada custom antes de gravar ou carregar. Levanta ValueError."""
    if not isinstance(game_id, str) or not VALID_ID.fullmatch(game_id):
        raise ValueError("id inválido: use letras minúsculas, números, '-' ou '_' (2 a 32)")
    if game_id in BUILTIN:
        raise ValueError(f"id reservado por um jogo embutido: {game_id}")
    if not isinstance(entry, dict):
        raise ValueError("entrada do jogo deve ser um objeto")
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise ValueError("name inválido")
    provider = entry.get("provider")
    if provider not in PROVIDERS:
        raise ValueError(f"provider inválido; use um de {PROVIDERS}")
    stop = entry.get("stop")
    if stop not in STOP_MODES:
        raise ValueError(f"stop inválido; use um de {STOP_MODES}")
    executable = entry.get("executable")
    if not isinstance(executable, str) or not executable:
        raise ValueError("executable é obrigatório")
    exe_path = Path(executable)
    if exe_path.is_absolute() or ".." in exe_path.parts or "\\" in executable:
        raise ValueError("executable deve ser um caminho relativo, sem '..' nem '\\'")
    port = entry.get("port")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("port inválida")
    if provider == "steam":
        appid = entry.get("appid")
        if not isinstance(appid, str) or not appid.isdigit():
            raise ValueError("appid do SteamCMD deve ser uma string numérica")
    persistent = entry.get("persistent", {})
    if not isinstance(persistent, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in persistent.items()
    ):
        raise ValueError("persistent deve mapear caminhos relativos (string) para destinos (string)")
    for relative, destination in persistent.items():
        for value in (relative, destination):
            path = Path(value)
            if path.is_absolute() or ".." in path.parts or "\\" in value:
                raise ValueError("persistent não aceita caminhos absolutos, '..' nem '\\'")
    return True


def load_custom(root):
    """Lê e valida config/custom_games.json. Ignora o arquivo ausente."""
    path = Path(root) / "config" / CUSTOM_FILE
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as error:
        raise ValueError(f"custom_games.json inválido: {error}") from None
    if not isinstance(raw, dict):
        raise ValueError("custom_games.json deve ser um objeto {id: entrada}")
    games = {}
    for game_id, entry in raw.items():
        validate_custom_entry(game_id, entry)
        clean = {"name": entry["name"], "provider": entry["provider"],
                 "executable": entry["executable"], "stop": entry["stop"],
                 "port": entry["port"], "custom": True,
                 "persistent": entry.get("persistent", {})}
        if entry["provider"] == "steam":
            clean["appid"] = entry["appid"]
        games[game_id] = clean
    return games


def catalog(root):
    """Retorna o catálogo mesclado: embutidos + custom. Custom nunca sobrescreve embutido."""
    merged = dict(GAMES)
    merged.update(load_custom(root))
    return merged


def defaults(game, games=None):
    games = games or GAMES
    meta = games[game]
    cfg = {"enabled": False, "name": meta["name"], "port": meta["port"],
           "stop_timeout": 180, "start_timeout": 30, "extra_args": []}
    if meta.get("custom"):
        # Jogos custom são genéricos: argumentos e opções específicas ficam aqui.
        cfg.update(launch_args=[])
        if meta["provider"] in ("mojang", "hytale"):
            cfg.update(java="java", heap="4G")
        if meta["provider"] == "mojang":
            cfg.update(version="latest", eula_accepted=False)
        if meta["provider"] == "hytale":
            cfg.update(downloader="", patchline="release")
        if meta["stop"] in ("source", "web"):
            cfg.update(rcon_password="", rcon_port=25575, query_port=27015)
        if meta["stop"] == "hook":
            cfg.update(stop_hook="", shutdown_verified=False)
        return cfg
    if game == "valheim":
        cfg.update(server_name="Meu Servidor", world="Dedicated", password="", public=True)
    if game in ("conan", "rust"):
        cfg.update(rcon_password="", rcon_port=25575 if game == "conan" else 28016,
                   query_port=27015 if game == "conan" else 28017, max_players=10)
    if game == "rust":
        cfg.update(world_size=3000, seed=12345)
    if game in ("minecraft", "hytale"):
        cfg.update(java="java", heap="4G")
    if game == "minecraft":
        cfg.update(version="latest", eula_accepted=False)
    if game == "hytale":
        cfg.update(downloader="", patchline="release")
    if game == "smalland":
        cfg.update(stop_hook="", launch_args=[], shutdown_verified=False)
    return cfg


def persistent_links(game, games=None):
    games = games or GAMES
    meta = games.get(game, {})
    if meta.get("custom"):
        return dict(meta.get("persistent", {}))
    # Destinos relativos a data/. Links só são criados após o download terminar.
    return {
        "conan": {"ConanSandbox/Saved": "Saved", "ConanSandbox/Mods": "Mods"},
        "rust": {"server": "server"},
        "smalland": {"SMALLAND/Saved": "Saved"},
    }.get(game, {})


def launch(game, cfg, current, data, games=None):
    games = games or GAMES
    meta = games[game]
    current, data = Path(current), Path(data)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = str(current / "linux64") + ":" + env.get("LD_LIBRARY_PATH", "")
    exe = str(current / meta["executable"])
    cwd = current
    if meta.get("custom"):
        # Perfil genérico por provedor. Sem argumentos especiais além dos revisados no JSON.
        if meta["provider"] in ("mojang", "hytale"):
            cwd = data
            args = [cfg["java"], f'-Xmx{cfg["heap"]}', "-jar", exe, *cfg["launch_args"]]
            if meta["provider"] == "hytale":
                env["HYTALE_DISABLE_UPDATES"] = "1"
        else:
            args = [exe] + cfg["launch_args"]
        return args + cfg["extra_args"], cwd, env
    if game == "valheim":
        env["SteamAppId"] = "892970"
        args = [exe, "-name", cfg["server_name"], "-world", cfg["world"],
                "-password", cfg["password"], "-port", str(cfg["port"]),
                "-public", "1" if cfg["public"] else "0", "-savedir", str(data)]
    elif game == "conan":
        env["SteamAppId"] = "440900"
        args = [exe, "ConanSandbox", "-log", "-stdout", "-FullStdOutLogOutput",
                f'-Port={cfg["port"]}', f'-QueryPort={cfg["query_port"]}',
                f'-MaxPlayers={cfg["max_players"]}']
    elif game == "rust":
        args = [exe, "-batchmode", "-nographics", "+server.identity", "main",
                "+server.port", str(cfg["port"]), "+server.queryport", str(cfg["query_port"]),
                "+server.worldsize", str(cfg["world_size"]), "+server.seed", str(cfg["seed"]),
                "-logfile", "-"]
    elif game == "minecraft":
        cwd = data
        args = [cfg["java"], f'-Xmx{cfg["heap"]}', "-jar", exe, "nogui"]
    elif game == "hytale":
        cwd = data
        env["HYTALE_DISABLE_UPDATES"] = "1"
        args = [cfg["java"], f'-Xmx{cfg["heap"]}', "-jar", exe,
                "--assets", str(current / "Assets.zip"), "--bind", f'0.0.0.0:{cfg["port"]}']
    else:
        args = [exe] + cfg["launch_args"]
    return args + cfg["extra_args"], cwd, env
