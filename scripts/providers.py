"""Downloads isolados; nunca extraia um pacote sobre mundos ou configurações."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request
import zipfile

from catalog import GAMES

MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"


def download(url, destination, sha1=None):
    if not url.startswith("https://"):
        raise ValueError("Download exige HTTPS")
    digest = hashlib.sha1()
    with urllib.request.urlopen(url, timeout=60) as response, open(destination, "wb") as output:
        if not response.url.startswith("https://"):
            raise ValueError("Redirecionamento inseguro")
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    if sha1 and digest.hexdigest() != sha1:
        raise ValueError("Checksum do download não confere; versão atual preservada")


def read_json(url):
    if not url.startswith("https://"):
        raise ValueError("Metadados exigem HTTPS")
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def java_major(java):
    result = subprocess.run([java, "-version"], capture_output=True, text=True, check=True)
    match = re.search(r'version "(\d+)', result.stderr + result.stdout)
    if not match:
        raise ValueError("Não foi possível detectar a versão do Java")
    return int(match[1])


def fetch(game, cfg, stage, tools_dir, meta=None):
    stage = Path(stage)
    meta = meta or GAMES[game]
    provider = meta["provider"]
    if provider == "steam":
        steamcmd = shutil.which("steamcmd") or "/usr/games/steamcmd"
        subprocess.run([steamcmd, "+@sSteamCmdForcePlatformType", "linux",
                        "+force_install_dir", str(stage), "+login", "anonymous",
                        "+app_update", meta["appid"], "validate", "+quit"], check=True)
        manifest = stage / "steamapps" / f'appmanifest_{meta["appid"]}.acf'
        if not manifest.is_file() or not re.search(r'"StateFlags"\s+"4"', manifest.read_text()):
            raise ValueError("SteamCMD não confirmou instalação completa (StateFlags=4)")
        return {"provider": provider, "appid": meta["appid"]}
    if provider == "mojang":
        if not cfg.get("eula_accepted"):
            raise ValueError("Leia a EULA do Minecraft e defina eula_accepted=true para baixar")
        manifest = read_json(MANIFEST)
        version = manifest["latest"]["release"] if cfg["version"] == "latest" else cfg["version"]
        item = next((v for v in manifest["versions"] if v["id"] == version), None)
        if item is None:
            raise ValueError("Versão Minecraft não encontrada")
        metadata_file = stage / "version.json"
        download(item["url"], metadata_file, item["sha1"])
        metadata = json.loads(metadata_file.read_text())
        required = metadata.get("javaVersion", {}).get("majorVersion", 8)
        if java_major(cfg["java"]) < required:
            raise ValueError(f"Esta versão exige Java {required}")
        server = metadata["downloads"]["server"]
        download(server["url"], stage / "server.jar", server["sha1"])
        return {"provider": provider, "version": version, "java_major": required}
    downloader = Path(cfg["downloader"]).expanduser()
    if not downloader.is_file() or not os.access(downloader, os.X_OK):
        raise ValueError("Configure o caminho do Hytale Downloader oficial; veja docs/jogos.md")
    if java_major(cfg["java"]) < 25:
        raise ValueError("Hytale exige Java 25 ou superior")
    # O diretório estável preserva as credenciais OAuth do downloader entre execuções.
    tools_dir.mkdir(parents=True, exist_ok=True)
    archive = stage / "game.zip"
    subprocess.run([str(downloader.resolve()), "-patchline", cfg["patchline"],
                    "-download-path", str(archive)], cwd=tools_dir, check=True)
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            path = Path(member.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in member.filename:
                raise ValueError("Caminho inválido no ZIP")
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Link simbólico inesperado no ZIP")
        package.extractall(stage)
    archive.unlink()
    if not (stage / "Assets.zip").is_file():
        raise ValueError("Assets.zip ausente; layout do provedor pode ter mudado")
    return {"provider": provider, "patchline": cfg["patchline"]}
