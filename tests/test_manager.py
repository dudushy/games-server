import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from catalog import GAMES, defaults, catalog, load_custom, validate_custom_entry, launch, persistent_links
from manager import Manager, atomic_json, living, read_json
import providers
from rcon import packet, send, source_commands
from status_site import handler
from http.server import ThreadingHTTPServer
import urllib.error
import urllib.request


class ManagerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="games-test-", dir="/tmp")
        self.manager = Manager(self.tmp.name)
        self.manager.initialize()

    def tearDown(self):
        run = self.manager.run_state()
        if living(run):
            os.killpg(run["pid"], signal.SIGTERM)
            for _ in range(40):
                if not living(run):
                    break
                time.sleep(0.05)
        self.manager.tmux("kill-server", check=False)
        self.tmp.cleanup()

    def configure(self, game):
        cfg = defaults(game)
        cfg.update(enabled=True, password="test-password", rcon_password="private-test-password", eula_accepted=True)
        atomic_json(self.manager.root / "config" / f"{game}.json", cfg)
        return cfg

    def fake_release(self, game):
        base, current, data = self.manager.paths(game)
        release = base / "releases/first"
        release.mkdir(parents=True)
        data.mkdir()
        current.symlink_to(release, target_is_directory=True)
        exe = release / GAMES[game]["executable"]
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text("fake binary")
        return exe

    def test_failed_download_keeps_current_and_data(self):
        self.configure("conan")
        self.fake_release("conan")
        _, current, data = self.manager.paths("conan")
        (data / "world.db").write_text("original")
        old = current.resolve()
        def failure(*args):
            raise ValueError("network failure")
        with patch("manager.fetch", failure), self.assertRaisesRegex(ValueError, "network"):
            self.manager.install("conan")
        self.assertEqual(current.resolve(), old)
        self.assertEqual((data / "world.db").read_text(), "original")

    def test_successful_update_cannot_overwrite_conan_settings(self):
        self.configure("conan")
        self.fake_release("conan")
        _, current, data = self.manager.paths("conan")
        settings = data / "Saved/Config/LinuxServer/ServerSettings.ini"
        settings.parent.mkdir(parents=True)
        settings.write_text("custom settings")
        def fake_fetch(game, cfg, stage, tools, meta=None):
            exe = stage / GAMES[game]["executable"]
            exe.parent.mkdir(parents=True)
            exe.write_text("new binary")
            exe.chmod(0o700)
            defaults_dir = stage / "ConanSandbox/Saved/Config/LinuxServer"
            defaults_dir.mkdir(parents=True)
            (defaults_dir / "ServerSettings.ini").write_text("vendor default")
            return {"provider": "fake"}
        with patch("manager.fetch", fake_fetch):
            self.manager.install("conan")
        self.assertEqual(settings.read_text(), "custom settings")
        self.assertEqual((current / "ConanSandbox/Saved/Config/LinuxServer/ServerSettings.ini").read_text(), "custom settings")
        self.assertTrue((current / "ConanSandbox/Saved").is_symlink())

    def test_lock_refuses_concurrent_mutations(self):
        with self.manager.lock():
            with self.assertRaisesRegex(ValueError, "Outra operação"):
                with Manager(self.tmp.name).lock():
                    pass

    def test_smalland_does_not_start_with_unverified_shutdown(self):
        cfg = self.configure("smalland")
        with self.assertRaisesRegex(ValueError, "pendente"):
            self.manager.validate_config("smalland", cfg, for_start=True)

    def test_minecraft_download_requires_explicit_eula(self):
        cfg = defaults("minecraft")
        with patch("providers.read_json") as network:
            with self.assertRaisesRegex(ValueError, "EULA"):
                providers.fetch("minecraft", cfg, Path(self.tmp.name), Path(self.tmp.name))
            network.assert_not_called()

    def test_checksum_mismatch_does_not_pass_validation(self):
        response = io.BytesIO(b"wrong contents")
        response.url = "https://example.test/download"
        with patch("urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "Checksum"):
                providers.download(response.url, Path(self.tmp.name) / "download", "0" * 40)

    def test_status_does_not_expose_passwords_or_paths(self):
        self.configure("conan")
        payload = json.dumps(self.manager.status())
        self.assertNotIn("private-test-password", payload)
        self.assertNotIn(self.tmp.name, payload)
        self.assertIsNone(json.loads(payload)["active_game"])

    def test_rcon_changes_preserve_other_ini_settings(self):
        cfg = self.configure("conan")
        self.fake_release("conan")
        path = self.manager.paths("conan")[2] / "Saved/Config/LinuxServer/Game.ini"
        path.parent.mkdir(parents=True)
        path.write_text("[Other]\nKeep=42\n[RconPlugin]\nRconPassword=old\nRconPort=9\n")
        self.manager.prepare_data("conan", cfg)
        self.manager.prepare_data("conan", cfg)
        self.assertIn("Keep=42", path.read_text())
        self.assertEqual(path.read_text().count("RconPassword="), 1)

    def simulated_valheim(self):
        cfg = self.configure("valheim")
        exe = self.fake_release("valheim")
        exe.write_text('''#!/usr/bin/env python3
import signal, sys, time
from pathlib import Path
data = Path(sys.argv[sys.argv.index('-savedir') + 1])
def stop(*_):
    if (data / 'ignore-stop').exists():
        return
    (data / 'saved').write_text('world saved')
    sys.exit(0)
signal.signal(signal.SIGINT, stop)
print('fake server ready', flush=True)
while True: time.sleep(0.1)
''')
        exe.chmod(0o700)
        return cfg

    def simulated_minecraft(self):
        cfg = self.configure("minecraft")
        self.fake_release("minecraft")
        java = self.manager.root / "fake-java"
        java.write_text('''#!/usr/bin/env python3
import sys
from pathlib import Path
if '-version' in sys.argv:
    print('openjdk version "25.0.1"', file=sys.stderr)
    sys.exit(0)
Path('started').write_text('started')
for line in sys.stdin:
    if line.strip() == 'save-all flush': Path('saved').write_text('saved')
    if line.strip() == 'stop': break
''')
        java.chmod(0o700)
        cfg["java"] = str(java)
        atomic_json(self.manager.root / "config/minecraft.json", cfg)

    def test_real_tmux_switch_waits_for_save_then_starts_next_game(self):
        self.simulated_valheim()
        self.simulated_minecraft()
        self.manager.start("valheim")
        self.assertTrue(living(self.manager.run_state()))
        self.manager.switch("minecraft")
        self.assertTrue((self.manager.paths("valheim")[2] / "saved").exists())
        self.assertEqual(self.manager.status()["active_game"], "minecraft")
        self.manager.stop()
        self.assertTrue((self.manager.paths("minecraft")[2] / "saved").exists())
        self.assertFalse(living(self.manager.run_state()))

    def test_stop_timeout_does_not_start_target_or_kill_original(self):
        cfg = self.simulated_valheim()
        cfg["stop_timeout"] = 1
        atomic_json(self.manager.root / "config/valheim.json", cfg)
        self.simulated_minecraft()
        data = self.manager.paths("valheim")[2]
        (data / "ignore-stop").touch()
        self.manager.start("valheim")
        with self.assertRaisesRegex(ValueError, "Encerramento não confirmado"):
            self.manager.switch("minecraft")
        self.assertEqual(self.manager.status()["active_game"], "valheim")
        self.assertFalse((self.manager.paths("minecraft")[2] / "started").exists())
        self.assertTrue((self.manager.runtime / "blocked.json").exists())
        (data / "ignore-stop").unlink()
        self.manager.stop()

    def test_invalid_target_leaves_current_running(self):
        self.simulated_valheim()
        self.manager.start("valheim")
        with self.assertRaises(ValueError):
            self.manager.switch("minecraft")
        self.assertTrue(living(self.manager.run_state()))
        self.assertFalse((self.manager.paths("valheim")[2] / "saved").exists())
        self.manager.stop()

    def test_stop_clears_desired_but_service_stop_preserves_it(self):
        self.simulated_valheim()
        self.manager.start("valheim")
        self.manager.stop(preserve_desired=True)
        self.assertEqual(read_json(self.manager.runtime / "desired.json")["game"], "valheim")
        self.assertEqual(read_json(self.manager.runtime / "blocked.json")["reason"], "service-stopped")
        self.manager.stop()
        self.assertIsNone(read_json(self.manager.runtime / "desired.json")["game"])

    def test_site_has_no_private_file_or_control_routes(self):
        self.configure("conan")
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.manager))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urllib.request.urlopen(base + "/api/status") as response:
                self.assertNotIn(b"private-test-password", response.read())
            for route in ("/config/conan.json", "/../config/conan.json", "/stop"):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(base + route)
                self.assertEqual(error.exception.code, 404)
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(base + "/api/status", data=b"stop", method="POST"))
            self.assertEqual(error.exception.code, 501)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class CustomCatalogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="games-custom-", dir="/tmp")
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write_custom(self, data):
        atomic_json(self.root / "config" / "custom_games.json", data)

    def valid_steam_entry(self):
        return {"name": "Palworld", "provider": "steam", "appid": "2394010",
                "executable": "PalServer.sh", "stop": "console", "port": 8211}

    def test_missing_custom_file_yields_empty(self):
        self.assertEqual(load_custom(self.root), {})

    def test_merge_adds_custom_without_overwriting_builtin(self):
        self.write_custom({"palworld": self.valid_steam_entry()})
        merged = catalog(self.root)
        self.assertIn("palworld", merged)
        self.assertTrue(merged["palworld"]["custom"])
        # Todos os embutidos continuam presentes e intactos.
        for builtin in GAMES:
            self.assertEqual(merged[builtin], GAMES[builtin])

    def test_custom_cannot_shadow_builtin_id(self):
        entry = self.valid_steam_entry()
        entry["name"] = "Fake Valheim"
        self.write_custom({"valheim": entry})
        with self.assertRaisesRegex(ValueError, "reservado"):
            load_custom(self.root)

    def test_rejects_path_traversal_in_executable(self):
        entry = self.valid_steam_entry()
        entry["executable"] = "../escape/binary"
        with self.assertRaisesRegex(ValueError, "relativo"):
            validate_custom_entry("palworld", entry)

    def test_rejects_absolute_executable(self):
        entry = self.valid_steam_entry()
        entry["executable"] = "/usr/bin/evil"
        with self.assertRaisesRegex(ValueError, "relativo"):
            validate_custom_entry("palworld", entry)

    def test_rejects_non_numeric_appid(self):
        entry = self.valid_steam_entry()
        entry["appid"] = "not-a-number"
        with self.assertRaisesRegex(ValueError, "appid"):
            validate_custom_entry("palworld", entry)

    def test_rejects_invalid_stop_mode(self):
        entry = self.valid_steam_entry()
        entry["stop"] = "kill-9"
        with self.assertRaisesRegex(ValueError, "stop"):
            validate_custom_entry("palworld", entry)

    def test_rejects_invalid_provider(self):
        entry = self.valid_steam_entry()
        entry["provider"] = "torrent"
        with self.assertRaisesRegex(ValueError, "provider"):
            validate_custom_entry("palworld", entry)

    def test_rejects_bad_id(self):
        with self.assertRaisesRegex(ValueError, "id inválido"):
            validate_custom_entry("Bad Id!", self.valid_steam_entry())

    def test_rejects_out_of_range_port(self):
        entry = self.valid_steam_entry()
        entry["port"] = 70000
        with self.assertRaisesRegex(ValueError, "port"):
            validate_custom_entry("palworld", entry)

    def test_rejects_traversal_in_persistent(self):
        entry = self.valid_steam_entry()
        entry["persistent"] = {"Saved": "../../etc"}
        with self.assertRaisesRegex(ValueError, "persistent"):
            validate_custom_entry("palworld", entry)

    def test_defaults_for_custom_steam_have_launch_args(self):
        self.write_custom({"palworld": self.valid_steam_entry()})
        games = catalog(self.root)
        cfg = defaults("palworld", games)
        self.assertEqual(cfg["launch_args"], [])
        self.assertEqual(cfg["port"], 8211)

    def test_launch_custom_steam_uses_generic_profile(self):
        self.write_custom({"palworld": self.valid_steam_entry()})
        games = catalog(self.root)
        cfg = defaults("palworld", games)
        cfg["launch_args"] = ["-useperfthreads"]
        args, cwd, env = launch("palworld", cfg, "/tmp/current", "/tmp/data", games)
        self.assertTrue(args[0].endswith("PalServer.sh"))
        self.assertIn("-useperfthreads", args)

    def test_launch_custom_mojang_uses_java_jar(self):
        entry = {"name": "Paper", "provider": "mojang", "executable": "server.jar",
                 "stop": "console", "port": 25565}
        self.write_custom({"paper": entry})
        games = catalog(self.root)
        cfg = defaults("paper", games)
        args, cwd, env = launch("paper", cfg, "/tmp/current", "/tmp/data", games)
        self.assertEqual(args[0], "java")
        self.assertIn("-jar", args)
        self.assertEqual(str(cwd), "/tmp/data")

    def test_add_game_writes_and_manager_sees_it(self):
        manager = Manager(self.root)
        manager.initialize()
        inputs = iter(["palworld", "Palworld", "steam", "2394010", "PalServer.sh",
                       "console", "8211", "", ""])
        with patch("builtins.input", lambda *_: next(inputs)), patch("sys.stdin.isatty", return_value=True):
            manager.add_game()
        self.assertIn("palworld", manager.games)
        self.assertEqual(manager.games["palworld"]["appid"], "2394010")

    def test_add_game_rejects_duplicate(self):
        self.write_custom({"palworld": self.valid_steam_entry()})
        manager = Manager(self.root)
        manager.initialize()
        inputs = iter(["palworld"])
        with patch("builtins.input", lambda *_: next(inputs)), patch("sys.stdin.isatty", return_value=True):
            with self.assertRaisesRegex(ValueError, "Já existe"):
                manager.add_game()


class RconTest(unittest.TestCase):
    def test_fragmented_auth_and_shutdown(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        received = []
        failures = []
        def serve():
            try:
                with listener.accept()[0] as client:
                    received.append(packet(client))
                    send(client, 1, 0, "")
                    body = struct.pack("<iii", 10, 1, 2) + b"\0\0"
                    for byte in body:
                        client.sendall(bytes([byte]))
                    received.append(packet(client))
            except Exception as error:
                failures.append(error)
        thread = threading.Thread(target=serve)
        thread.start()
        try:
            source_commands(listener.getsockname()[1], "secret-test", ["shutdown"])
            thread.join(timeout=5)
            self.assertFalse(failures)
            self.assertEqual(received[-1][2], "shutdown")
        finally:
            listener.close()


if __name__ == "__main__":
    unittest.main()
