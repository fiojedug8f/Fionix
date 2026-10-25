"""Tests for the Stage 3 launcher core (no network access required)."""

from __future__ import annotations

import json
import shutil
import threading
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from src.core import launcher
from src.core.config_manager import ConfigManager
from src.core.launcher import (
    Instance,
    InstallCancelled,
    LauncherService,
    format_last_played,
    format_playtime,
    offline_uuid,
)


class LauncherCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_root = Path(__file__).resolve().parent / ".tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.root = temp_root / f"case-{uuid.uuid4().hex}"
        self.data_dir = self.root / "Fionix"
        self.data_dir.mkdir(parents=True)
        self.config = ConfigManager(self.data_dir)
        self.service = LauncherService(self.config)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    # ------------------------------------------------------------- helpers
    @staticmethod
    def fake_install(version: str, directory: str, callback: dict) -> None:
        target = Path(directory)
        version_dir = target / "versions" / version
        version_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "id": version,
            "type": "release",
            "mainClass": "net.minecraft.client.main.Main",
            "libraries": [],
            "assets": "legacy",
            "javaVersion": {"majorVersion": 17, "component": "java-runtime-gamma"},
            "arguments": {
                "jvm": [],
                "game": [
                    "--username",
                    "${auth_player_name}",
                    "--uuid",
                    "${auth_uuid}",
                ],
            },
        }
        (version_dir / f"{version}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        callback["setStatus"]("Download Libraries")
        callback["setMax"](3)
        callback["setProgress"](1)
        callback["setProgress"](3)
        callback["setStatus"]("Download Assets")
        callback["setMax"](2)
        callback["setProgress"](2)
        callback["setStatus"]("Installation complete")

    def _seed_instance(self, version: str = "1.20.1") -> Instance:
        instance_dir = self.service.instances_dir / f"Vanilla_{version}"
        instance_dir.mkdir(parents=True, exist_ok=True)
        version_dir = instance_dir / "versions" / version
        version_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "id": version,
            "type": "release",
            "mainClass": "net.minecraft.client.main.Main",
            "libraries": [],
            "assets": "legacy",
            "arguments": {
                "jvm": [],
                "game": [
                    "--username",
                    "${auth_player_name}",
                    "--uuid",
                    "${auth_uuid}",
                ],
            },
        }
        (version_dir / f"{version}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        instance = Instance(
            path=instance_dir,
            version=version,
            name=f"Vanilla {version}",
            created_at="2026-10-24T10:00:00",
            java_major=17,
        )
        instance.save()
        return instance

    # --------------------------------------------------------------- data
    def test_offline_uuid_and_formatters(self) -> None:
        first = offline_uuid("FionixPlayer")
        second = offline_uuid("FionixPlayer")
        self.assertEqual(first, second)
        self.assertEqual(uuid.UUID(first).version, 3)
        self.assertNotEqual(first, offline_uuid("OtherPlayer"))

        self.assertEqual(format_playtime(0), "0 мин")
        self.assertEqual(format_playtime(61), "1 мин")
        self.assertEqual(format_playtime(3600), "1 ч")
        self.assertEqual(format_playtime(7384), "2 ч 03 мин")
        self.assertEqual(format_last_played(None), "Ещё не запускался")

    def test_instance_metadata_roundtrip(self) -> None:
        instance_dir = self.service.instances_dir / "Vanilla_1.20.1"
        instance_dir.mkdir()
        instance = Instance(
            path=instance_dir,
            version="1.20.1",
            name="Vanilla 1.20.1",
            created_at="2026-10-24T10:00:00",
            java_major=17,
            playtime_seconds=3600,
            last_played_at="2026-10-24T12:00:00",
        )
        instance.save()
        loaded = Instance.load(instance_dir)
        self.assertEqual(loaded.playtime_seconds, 3600)
        self.assertEqual(loaded.last_played_at, "2026-10-24T12:00:00")
        self.assertEqual(loaded.java_major, 17)

        loaded.add_playtime(125)
        self.assertEqual(loaded.playtime_seconds, 3725)
        self.assertIn(
            '"version": "1.20.1"',
            (instance_dir / "instance_config.json").read_text("utf-8"),
        )
        self.assertFalse((instance_dir / "instance.json").exists())

    # ------------------------------------------------------------ install
    def test_install_creates_exact_folder_and_metadata(self) -> None:
        progress: list[int] = []
        runtime_function_seen: list[str] = []

        def fake_install(version: str, directory: str, callback: dict) -> None:
            runtime_function_seen.append(
                getattr(launcher.mc_install.install_jvm_runtime, "__name__", "")
            )
            LauncherCoreTests.fake_install(version, directory, callback)

        with patch.object(launcher.mc_install, "install_minecraft_version", fake_install):
            instance = self.service.create_vanilla_instance(
                "1.20.1", progress=lambda p, _t, _d: progress.append(p)
            )

        expected = self.service.instances_dir / "Vanilla_1.20.1"
        self.assertEqual(instance.path, expected)
        self.assertTrue((expected / "instance_config.json").is_file())
        self.assertEqual(instance.java_major, 17)
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(progress[-1], 100)
        self.assertIn("_skip", runtime_function_seen)
        self.assertEqual(list(self.service.staging_dir.iterdir()), [])

        # A second call should return the existing instance and not reinstall.
        called = []
        with patch.object(
            launcher.mc_install,
            "install_minecraft_version",
            lambda *args, **kwargs: called.append(True),
        ):
            again = self.service.create_vanilla_instance("1.20.1")
        self.assertEqual(again.path, expected)
        self.assertEqual(called, [])

    def test_cancel_cleans_staging_folder(self) -> None:
        cancel = threading.Event()
        cancel.set()

        with patch.object(
            launcher.mc_install, "install_minecraft_version", self.fake_install
        ):
            with self.assertRaises(InstallCancelled):
                self.service.create_vanilla_instance("1.20.1", cancel_event=cancel)

        self.assertFalse((self.service.instances_dir / "Vanilla_1.20.1").exists())
        leftovers = [path for path in self.service.staging_dir.iterdir()]
        self.assertEqual(leftovers, [])

    # -------------------------------------------------------------- java
    def test_managed_java_and_launch_command(self) -> None:
        self._seed_instance()
        instance = self.service.instance_for_version("1.20.1")
        self.assertIsNotNone(instance)
        assert instance is not None

        runtime_bin = self.service.runtime_dir / "temurin-17" / "jdk-17" / "bin"
        runtime_bin.mkdir(parents=True)
        (runtime_bin / "java.exe").write_bytes(b"")
        (runtime_bin / "javaw.exe").write_bytes(b"")
        runtime = self.service.managed_java(17)
        self.assertIsNotNone(runtime)
        assert runtime is not None
        self.assertEqual(runtime.path.name, "javaw.exe")

        instance.memory_mb = 8192
        command = self.service.build_launch_command(instance, runtime)
        self.assertEqual(Path(command[0]), runtime.path)
        self.assertIn("-Xmx8192M", command)
        self.assertIn("FionixPlayer", command)
        self.assertIn(offline_uuid("FionixPlayer"), command)

    # ----------------------------------------------------- stage 3 features
    def test_legacy_instance_metadata_is_migrated(self) -> None:
        instance_dir = self.service.instances_dir / "Vanilla_1.20.1"
        instance_dir.mkdir()
        legacy = {
            "schema_version": 1,
            "name": "Vanilla 1.20.1",
            "version": "1.20.1",
            "loader": "vanilla",
            "created_at": "2026-10-20T10:00:00",
            "last_played_at": None,
            "playtime_seconds": 90,
            "java_major": 17,
        }
        (instance_dir / "instance.json").write_text(
            json.dumps(legacy), encoding="utf-8"
        )
        instances = self.service.list_instances()
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0].effective_launch_version, "1.20.1")
        self.assertTrue((instance_dir / "instance_config.json").is_file())
        self.assertFalse((instance_dir / "instance.json").exists())

    def test_content_toggle_and_backup(self) -> None:
        instance = self._seed_instance()
        mods = instance.path / "mods"
        mods.mkdir()
        (mods / "cool-mod.jar").write_bytes(b"jar-bytes")
        (mods / "old-mod.jar.disabled").write_bytes(b"old")
        (mods / "readme.txt").write_text("hello", encoding="utf-8")

        content = self.service.list_content(instance, "mods")
        self.assertEqual(len(content), 3)
        self.assertTrue(any(item.enabled and item.display_name == "cool-mod.jar" for item in content))
        self.assertTrue(any(not item.enabled and item.display_name == "old-mod.jar" for item in content))

        disabled = self.service.toggle_content(
            instance, "mods", mods / "cool-mod.jar", False
        )
        self.assertTrue(disabled.name.endswith(".disabled"))
        self.assertFalse((mods / "cool-mod.jar").exists())

        enabled = self.service.toggle_content(instance, "mods", disabled, True)
        self.assertEqual(enabled.name, "cool-mod.jar")

        # Backup only packs mods/config and lands in the global backups folder.
        (instance.path / "config").mkdir(exist_ok=True)
        (instance.path / "config" / "settings.cfg").write_text("x=1", encoding="utf-8")
        archive = self.service.create_backup(instance)
        self.assertTrue(archive.is_file())
        self.assertEqual(archive.parent, self.data_dir / "backups")
        with zipfile.ZipFile(archive) as zf:
            names = set(zf.namelist())
        self.assertIn("mods/cool-mod.jar", names)
        self.assertIn("config/settings.cfg", names)
        self.assertNotIn("instance_config.json", names)

    def test_fabric_instance_uses_loader_metadata(self) -> None:
        class FakeLoader:
            def is_minecraft_version_supported(self, version: str) -> bool:
                return True

            def get_latest_loader_version(self, version: str) -> str:
                return "0.16.0"

            def install(self, version, directory, *, loader_version, callback, java):
                callback["setStatus"]("Installing Fabric")
                callback["setMax"](2)
                callback["setProgress"](2)
                return f"fabric-loader-{loader_version}-{version}"

        fake_java = launcher.JavaRuntime(
            path=Path("C:/fake/java.exe"), major=17, source="Temurin"
        )
        with (
            patch.object(launcher.mc_install, "install_minecraft_version", self.fake_install),
            patch.object(launcher.mc_mod_loader, "get_mod_loader", return_value=FakeLoader()),
            patch.object(self.service, "ensure_java", return_value=fake_java),
        ):
            instance = self.service.create_instance("1.20.1", "fabric")

        self.assertEqual(instance.path.name, "Fabric_1.20.1")
        self.assertEqual(instance.loader, "fabric")
        self.assertEqual(instance.loader_version, "0.16.0")
        self.assertEqual(instance.launch_version, "fabric-loader-0.16.0-1.20.1")
        self.assertEqual(instance.memory_mb, self.config.memory_mb)
        payload = json.loads(
            (instance.path / "instance_config.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["loader"], "fabric")
        self.assertEqual(payload["launch_version"], "fabric-loader-0.16.0-1.20.1")

    def test_optifine_is_a_supported_loader(self) -> None:
        self.assertEqual(launcher.loader_label("optifine"), "OptiFine")
        self.assertEqual(launcher.normalize_loader("optifine"), "optifine")

    def test_custom_java_validation(self) -> None:
        java_file = self.root / "custom" / "java.exe"
        java_file.parent.mkdir()
        java_file.write_bytes(b"")
        with patch.object(self.service, "_probe_java", return_value=(21, "21.0.1")):
            runtime = self.service.java_runtime_from_path(java_file, 17)
        self.assertEqual(runtime.major, 21)
        self.assertEqual(runtime.source, "Пользовательская")
        with patch.object(self.service, "_probe_java", return_value=(8, "1.8.0_402")):
            with self.assertRaises(launcher.LauncherError):
                self.service.java_runtime_from_path(java_file, 17)

    def test_version_catalog_keeps_pinned_versions(self) -> None:
        from datetime import datetime, timezone

        fetched = [
            launcher.VersionEntry(
                version=f"26.{index}",
                release_time=datetime(2026, 1, index + 1, tzinfo=timezone.utc),
            )
            for index in range(16)
        ]
        catalog = self.service.merge_catalog(fetched)
        versions = [entry.version for entry in catalog]
        self.assertEqual(len(versions), len(set(versions)))
        for pinned in ("1.21.1", "1.21", "1.20.1"):
            self.assertIn(pinned, versions)


if __name__ == "__main__":
    unittest.main()
