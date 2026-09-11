# Modpacks de Minecraft (Forge) — montagem manual

Os provedores embutidos não montam modpacks: `mojang` baixa apenas o JAR vanilla
oficial. Um modpack Forge (ex.: FTB, CurseForge) precisa de um loader (Forge), de
uma pasta `mods/` e de `config/`. Este guia descreve como montar um **server pack**
de modpack manualmente e integrá-lo ao gerenciador como um jogo custom `mojang`,
sem usar `install` (a montagem é feita à mão, uma única vez).

O exemplo usa **FTB Presents Stoneblock 2** (Minecraft 1.12.2, Forge
14.23.5.2846), mas o procedimento vale para qualquer server pack Forge/legado.

## Pré-requisitos

- O **server pack** do modpack (não o pacote de cliente). Um server pack traz o JAR
  do Forge (ex.: `FTBserver-<mc>-<forge>-universal.jar`), `mods/`, `config/`,
  `libraries/` e scripts de start. O pacote de cliente (só `manifest.json` +
  `overrides/`) **não** serve: ele apenas referencia mods por ID e exige a API da
  CurseForge para baixá-los.
- O **Java correto** para a versão do Minecraft. Forge 1.12.2 exige **Java 8**.
  Instale via SDKMAN (veja [Ubuntu e dependências](ubuntu.md)):

  ```bash
  sdk install java 8.0.504+1-tem
  # caminho absoluto do binário (usado no config do jogo):
  ls ~/.sdkman/candidates/java/8.0.504+1-tem/bin/java
  ```

## Layout: o que vai na release e o que vai em `data/`

O perfil `mojang` do gerenciador roda o JAR com **`cwd = data/`** e o executável
apontado por `current/<executable>` (na release). Isso impõe onde cada coisa fica:

| Item | Onde | Por quê |
|---|---|---|
| JAR do Forge (`executable`) | **release** (`current/`) | é o `executable` do jogo custom |
| `libraries/`, `minecraft_server.<mc>.jar` | **release**, ao lado do JAR | o `Class-Path` do MANIFEST do Forge é **relativo ao JAR** |
| `mods/`, `config/`, `scripts/` | **`data/`** (cwd) | o FML procura mods e config **relativos ao diretório de trabalho** |
| mundo, `server.properties`, listas | **`data/`** (cwd) | dados de runtime; entram no backup |

Colocar `libraries/`/`minecraft_server.jar` em `data/` faz o Forge falhar com
`ClassNotFoundException: net.minecraft.launchwrapper.Launch`, porque o `Class-Path`
do JAR aponta para `libraries/` **ao lado do próprio JAR**, não ao cwd. Por isso
esses dois ficam na release; `mods`/`config`/`scripts` ficam em `data/`.

> Evite ligar `mods`/`config` por link simbólico para dentro de `data/`: o `backup`
> do gerenciador recusa `data/` com links simbólicos.

## Passo a passo

Com `GAMES_ROOT=$HOME/.local/share/games-server` e o jogo `stoneblock2`:

1. **Crie a release e extraia o server pack:**

   ```bash
   BASE="$GAMES_ROOT/games/stoneblock2"
   REL="$BASE/releases/release-$(python3 -c 'import secrets;print(secrets.token_hex(8))')"
   mkdir -p "$REL" "$BASE/data"
   (cd "$REL" && unzip -q ~/Downloads/FTBPresentsStoneblock2Server_1.16.0.zip)
   ```

2. **Baixe os JARs que faltam.** O `FTBInstall.sh` tenta a URL S3 antiga da Mojang,
   que está morta (HTTP 404). O `launchwrapper` ainda vem de `libraries.minecraft.net`
   e é baixado; o `minecraft_server.<mc>.jar` precisa vir da fonte atual, com
   verificação de SHA-1 (resolvida pelo manifesto oficial):

   ```bash
   (cd "$REL" && sh ./FTBInstall.sh)   # baixa o launchwrapper; falha só no server.jar
   python3 - "$REL" <<'PY'
   import json, urllib.request, hashlib, sys
   rel = sys.argv[1]
   m = json.load(urllib.request.urlopen("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json", timeout=60))
   v = next(x for x in m["versions"] if x["id"] == "1.12.2")
   srv = json.load(urllib.request.urlopen(v["url"], timeout=60))["downloads"]["server"]
   data = urllib.request.urlopen(srv["url"], timeout=120).read()
   assert hashlib.sha1(data).hexdigest() == srv["sha1"], "SHA1 não confere"
   open(rel + "/minecraft_server.1.12.2.jar", "wb").write(data)
   print("minecraft_server.1.12.2.jar OK")
   PY
   ```

3. **Organize o layout** (mods/config/scripts para `data/`; libraries e
   minecraft_server ficam na release, ao lado do JAR):

   ```bash
   mv "$REL/mods" "$REL/config" "$REL/scripts" "$REL/server-icon.png" "$BASE/data/"
   # 'libraries' e 'minecraft_server.<mc>.jar' PERMANECEM em "$REL"
   ```

4. **Crie o `release.json`** (o gerenciador lê `java_major` no preflight):

   ```bash
   python3 - "$REL" <<'PY'
   import json, sys, time
   rel = sys.argv[1]
   json.dump({"provider": "mojang", "version": "1.12.2", "java_major": 8,
              "modpack": "FTB Presents Stoneblock 2", "forge": "14.23.5.2846",
              "manual_build": True, "installed_at": time.time()},
             open(rel + "/release.json", "w"), indent=2, ensure_ascii=False)
   PY
   ```

5. **Ligue `current` à release:**

   ```bash
   ln -sfn "$REL" "$BASE/current"
   ```

6. **Cadastre o jogo custom** em `config/custom_games.json` (não use `add-game` com
   `persistent`, pois não vamos usar `install`):

   ```json
   {
     "stoneblock2": {
       "name": "Minecraft: FTB Stoneblock 2 (modpack)",
       "provider": "mojang",
       "executable": "FTBserver-1.12.2-14.23.5.2846-universal.jar",
       "stop": "console",
       "port": 25565
     }
   }
   ```

7. **Crie `config/stoneblock2.json`** apontando o Java 8 e o heap. `launch_args`
   deve conter `nogui`; `eula_accepted` precisa ser `true`:

   ```json
   {
     "enabled": true,
     "name": "Minecraft: FTB Stoneblock 2 (modpack)",
     "port": 25565,
     "stop_timeout": 180,
     "start_timeout": 120,
     "extra_args": [],
     "launch_args": ["nogui"],
     "java": "/home/USUARIO/.sdkman/candidates/java/8.0.504+1-tem/bin/java",
     "heap": "8G",
     "version": "1.12.2",
     "eula_accepted": true
   }
   ```

8. **Verifique e troque para o jogo:**

   ```bash
   ./start_server.sh status          # stoneblock2 deve aparecer configurado/instalado
   ./start_server.sh switch stoneblock2
   ./start_server.sh console         # acompanhe até "Done (Ns)!"; Ctrl+B, D para sair
   ```

   O parar usa o modo `console` (`save-all flush` + `stop`), salvando o mundo e
   fazendo backup antes da troca.

## Avisos importantes

- **Não rode `install stoneblock2`.** O provedor `mojang` baixaria o JAR **vanilla**
  numa release nova e ligaria `current` a ela, quebrando a montagem do modpack.
  Modpacks montados à mão são atualizados à mão (monte uma nova release e refaça o
  link `current`).
- **`start_timeout`**: modpacks grandes levam mais de 30s até "Done". O gerenciador
  só exige que o **processo** esteja vivo após o timeout (não o "Done"), mas use um
  valor folgado (ex.: 120) para evitar bloqueio em picos de I/O.
- **Java 8 e o esquema de versão legado**: o Java 8 se identifica como `1.8.0_xxx`.
  O gerenciador reconhece esse esquema e o trata como major 8 (veja `java_major` em
  `scripts/providers.py`).
- Warnings de mods (ex.: "missing the required element 'version'", "Can not get
  Fluid", módulos opcionais que não carregam) são comuns em packs 1.12.2 e não
  impedem o "Done". Erros fatais reais interrompem o boot antes do "Done".
