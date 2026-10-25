"""Unit tests for accounts, pack export and the updater (no network)."""

from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from src.core.accounts import Account, AccountManager, create_guest
from src.core.config_manager import ConfigManager
from src.core.exporter import (
    PackError,
    export_pack,
    read_pack,
    record_installed_mod,
)
from src.core.launcher import Instance
from src.core.market_api import MarketAPI, MarketProject
from src.core.theme import set_accent_color, set_theme, current_theme
from src.core.updater import is_newer, version_tuple


class Stage4CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parent / ".tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.root = root / f"stage4-{uuid.uuid4().hex}"
        self.data = self.root / "Fionix"
        self.data.mkdir(parents=True)
        self.config = ConfigManager(self.data)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_account_manager_guest_and_switching(self) -> None:
        manager = AccountManager(self.data)
        self.assertEqual(manager.accounts, [])
        first = manager.ensure_guest("Steve")
        self.assertEqual(first.provider, "guest")
        self.assertTrue(manager.path.is_file())
        second = manager.add(create_guest("Alex"))
        self.assertEqual(len(manager.accounts), 2)
        self.assertEqual(manager.active_id, second.id)
        self.assertTrue(manager.set_active(first.id))
        reloaded = AccountManager(self.data)
        self.assertEqual(reloaded.active_id, first.id)
        self.assertTrue(reloaded.remove(first.id))
        self.assertEqual(reloaded.current.id, second.id)
        payload = json.loads(reloaded.path.read_text(encoding="utf-8"))
        self.assertNotIn("password", json.dumps(payload))

    def test_account_from_dict_defaults(self) -> None:
        account = Account.from_dict(
            {"provider": "littleskin", "username": "SkinUser", "access_token": "t"}
        )
        self.assertEqual(account.provider, "littleskin")
        self.assertEqual(account.username, "SkinUser")
        self.assertTrue(account.uuid)

    def _instance(self, loader: str = "fabric") -> Instance:
        path = self.data / "instances" / f"{loader.title()}_1.20.1"
        path.mkdir(parents=True)
        (path / "mods").mkdir()
        (path / "mods" / "sodium.jar").write_bytes(b"x")
        instance = Instance(
            path=path,
            version="1.20.1",
            name="My Pack",
            created_at="2026-10-24T12:00:00",
            loader=loader,
            loader_version="0.16.0",
            launch_version="fabric-loader-0.16.0-1.20.1",
        )
        instance.save()
        return instance

    def test_export_pack_structure(self) -> None:
        instance = self._instance()
        record_installed_mod(
            instance,
            name="Sodium",
            version="0.5.0",
            source="modrinth",
            filename="sodium.jar",
        )
        target = export_pack(instance, self.root / "pack.fionixpack")
        payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(
            set(payload),
            {"version", "name", "mc_version", "loader", "mods"},
        )
        self.assertEqual(payload["version"], "1.0")
        self.assertEqual(payload["mc_version"], "1.20.1")
        self.assertEqual(payload["loader"], "fabric")
        self.assertEqual(payload["mods"][0]["name"], "Sodium")
        self.assertEqual(payload["mods"][0]["source"], "modrinth")
        self.assertNotIn("filename", payload["mods"][0])
        parsed = read_pack(target)
        self.assertEqual(parsed["mods"][0]["version"], "0.5.0")

    def test_import_pack_installs_modrinth_mods(self) -> None:
        from unittest.mock import MagicMock

        from src.core.exporter import import_pack
        from src.core.launcher import LauncherService

        instance = self._instance()
        pack = self.root / "import.fionixpack"
        pack.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "name": "Imported",
                    "mc_version": "1.20.1",
                    "loader": "fabric",
                    "mods": [
                        {"name": "Sodium", "version": "0.5.0", "source": "modrinth"},
                        {"name": "Local", "version": "", "source": "local"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        service = LauncherService(self.config)
        market = MagicMock()
        seen = []
        market.install_modrinth_spec.side_effect = lambda *args, **kwargs: seen.append(args)
        with patch.object(service, "create_instance", return_value=instance):
            imported, skipped = import_pack(service, market, pack)
        self.assertEqual(imported.name, "Imported")
        self.assertEqual(len(seen), 1)
        self.assertTrue(any("Local" in item for item in skipped))

    def test_invalid_pack_is_rejected(self) -> None:
        target = self.root / "bad.fionixpack"
        target.write_text('{"version": "9.0"}', encoding="utf-8")
        with self.assertRaises(PackError):
            read_pack(target)

    def test_updater_version_comparison(self) -> None:
        self.assertEqual(version_tuple("v1.2.3"), (1, 2, 3))
        self.assertTrue(is_newer("v1.0.1", "1.0.0"))
        self.assertTrue(is_newer("v1.1", "1.0.9"))
        self.assertFalse(is_newer("v1.0.0", "1.0.0"))
        self.assertFalse(is_newer("v0.9.9", "1.0.0"))

    def test_accent_theme_variant(self) -> None:
        try:
            set_theme("dark")
            set_accent_color("#22c55e")
            self.assertEqual(current_theme().accent.name(), "#22c55e")
            self.assertNotEqual(current_theme().accent_light.name(), "#8b5cf6")
        finally:
            set_accent_color("")
            set_theme("dark")

    def test_microsoft_token_exchange_is_public_client(self) -> None:
        from unittest.mock import patch
        from src.core import accounts

        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {"access_token": "token"}

        with patch.object(accounts.requests, "post", return_value=Response()) as post:
            token = accounts._microsoft_token_exchange(
                "one-time-code", "http://localhost"
            )
        self.assertEqual(token, "token")
        data = post.call_args.kwargs["data"]
        self.assertNotIn("client_secret", data)
        self.assertEqual(data["client_id"], accounts.CLIENT_ID)
        self.assertEqual(data["redirect_uri"], "http://localhost")
        self.assertEqual(data["grant_type"], "authorization_code")

    def test_microsoft_code_cannot_be_exchanged_twice(self) -> None:
        from unittest.mock import patch
        from src.core import accounts

        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {"access_token": "token"}

        code = "single-use-code-47"
        with patch.object(accounts.requests, "post", return_value=Response()) as post:
            accounts._microsoft_token_exchange(code, "http://localhost")
            with self.assertRaises(accounts.AccountError):
                accounts._microsoft_token_exchange(code, "http://localhost")
        self.assertEqual(post.call_count, 1)

    def test_microsoft_authorization_uses_root_config(self) -> None:
        from config import CLIENT_ID, REDIRECT_URL
        from src.core.accounts import microsoft_login_url

        url = microsoft_login_url("state-123")
        self.assertIn(CLIENT_ID, url)
        self.assertIn("login.microsoftonline.com/consumers", url)
        self.assertIn("XboxLive.signin%20offline_access", url)
        self.assertIn(REDIRECT_URL.replace(":", "%3A"), url)

    def test_modpack_installer_creates_instance_files_and_overrides(self) -> None:
        import json
        import zipfile
        from src.core.modpacks import ModpackInfo, install_modpack
        from src.core.market_api import MarketProject

        archive = self.root / "pack.mrpack"
        index = {
            "formatVersion": 1,
            "name": "Test Pack",
            "versionId": "1.0",
            "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.0"},
            "files": [
                {
                    "path": "mods/example.jar",
                    "downloads": ["https://example.invalid/example.jar"],
                    "hashes": {},
                }
            ],
        }
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("modrinth.index.json", json.dumps(index))
            zf.writestr("overrides/config/example.txt", "hello")
        project = MarketProject(
            "pack-id", "test-pack", "Test Pack", "tester", "A pack",
            "", 10, "modrinth", game_versions=("1.20.1",),
        )
        info = ModpackInfo(
            project=project,
            name="Test Pack",
            source="modrinth",
            version_id="1.0",
            version_name="1.0",
            mc_version="1.20.1",
            loader="fabric",
            loader_version="0.15.0",
            archive=archive,
            mod_files=("mods/example.jar",),
            files_manifest=tuple(index["files"]),
        )
        install_dir = self.root / "installed-pack"
        install_dir.mkdir()
        instance = Instance(
            path=install_dir,
            version="1.20.1",
            name="Test Pack",
            created_at="2026-10-24T12:00:00",
            loader="fabric",
        )

        class FakeService:
            def create_instance(self, version, loader, **kwargs):
                return instance

        class FakeApi:
            def download_file(self, url, parent, filename, **kwargs):
                parent.mkdir(parents=True, exist_ok=True)
                target = parent / filename
                target.write_bytes(b"jar")
                return target

        result = install_modpack(FakeService(), FakeApi(), info)
        self.assertIs(result, instance)
        self.assertTrue((install_dir / "mods" / "example.jar").is_file())
        self.assertEqual(
            (install_dir / "config" / "example.txt").read_text(encoding="utf-8"),
            "hello",
        )

    def test_delete_instance_is_scoped_to_instances_dir(self) -> None:
        from src.core.launcher import LauncherService

        service = LauncherService(self.config)
        path = service.instances_dir / "Fabric_1.20.1"
        path.mkdir()
        (path / "mods").mkdir()
        (path / "mods" / "x.jar").write_bytes(b"x")
        instance = Instance(
            path=path,
            version="1.20.1",
            name="Fabric 1.20.1",
            created_at="2026-10-24T12:00:00",
            loader="fabric",
        )
        instance.save()
        self.assertTrue(service.delete_instance(instance))
        self.assertFalse(path.exists())
        outside = self.root / "outside"
        outside.mkdir()
        bad = Instance(
            path=outside,
            version="1.20.1",
            name="Bad",
            created_at="2026-10-24T12:00:00",
        )
        with self.assertRaises(Exception):
            service.delete_instance(bad)
        self.assertTrue(outside.exists())

    def test_custom_instances_dir_and_global_java(self) -> None:
        custom = self.root / "Elsewhere" / "instances"
        self.config.update({"instances_path": str(custom)})
        from src.core.launcher import LauncherService

        service = LauncherService(self.config)
        self.assertEqual(service.instances_dir, custom)
        java_file = self.root / "java" / "java.exe"
        java_file.parent.mkdir()
        java_file.write_bytes(b"")
        self.config.update({"java": {"path": str(java_file), "auto": False}})
        with patch.object(service, "_probe_java", return_value=(21, "21.0.1")):
            runtime = service.preferred_java(17)
        self.assertIsNotNone(runtime)
        self.assertEqual(runtime.major, 21)

    def test_update_checks_are_offline_when_repo_is_placeholder(self) -> None:
        from src.core import updater

        with (
            patch.object(updater, "GITHUB_REPO", ""),
            patch.object(updater.requests, "get") as request,
        ):
            info = updater.check_for_updates("1.0.0")
        self.assertFalse(info.available)
        self.assertFalse(info.configured)
        request.assert_not_called()
        self.assertEqual(updater.NOT_CONFIGURED_MESSAGE, "Проверка обновлений недоступна (репозиторий не настроен)")

    def test_update_check_parses_github_release(self) -> None:
        from src.core import updater

        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "tag_name": "v1.2.0",
                    "html_url": "https://example.invalid/release",
                    "body": "Notes",
                    "assets": [
                        {
                            "name": "Fionix-Setup.exe",
                            "browser_download_url": "https://example.invalid/Fionix-Setup.exe",
                        }
                    ],
                }

        with (
            patch.object(updater, "GITHUB_REPO", "user/repo"),
            patch.object(updater.requests, "get", return_value=Response()),
        ):
            info = updater.check_for_updates("1.0.0")
        self.assertTrue(info.available)
        self.assertTrue(info.configured)
        self.assertEqual(info.display_latest, "1.2.0")
        self.assertEqual(info.url, "https://example.invalid/release")
        self.assertEqual(info.asset_name, "Fionix-Setup.exe")

    def test_update_download_saves_exe_asset(self) -> None:
        from src.core import updater

        class StreamingResponse:
            status_code = 200
            headers = {"Content-Length": "4"}

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size=1024):
                yield b"test"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        info = updater.UpdateInfo(
            available=True,
            current="1.0.0",
            latest="1.1.0",
            asset_url="https://example.invalid/Fionix.exe",
            asset_name="Fionix.exe",
        )
        download_dir = self.root / "update-download"
        download_dir.mkdir()
        with (
            patch.object(updater.requests, "get", return_value=StreamingResponse()),
            patch.object(updater.tempfile, "mkdtemp", return_value=str(download_dir)),
        ):
            target = updater.download_update(info)
        try:
            self.assertTrue(target.is_file())
            self.assertEqual(target.read_bytes(), b"test")
            self.assertEqual(target.name, "Fionix.exe")
        finally:
            target.unlink(missing_ok=True)
            target.parent.rmdir()

    def test_market_parses_modrinth_hits(self) -> None:
        api = MarketAPI(self.config)
        fake = {
            "hits": [
                {
                    "project_id": "AANobbMI",
                    "slug": "sodium",
                    "title": "Sodium",
                    "description": "Fast renderer",
                    "author": "jellysquid3",
                    "icon_url": "",
                    "downloads": 100,
                    "versions": ["1.20.1"],
                    "categories": ["fabric"],
                }
            ]
        }
        with patch.object(api, "_json", return_value=fake):
            projects = api.search_modrinth("sodium", "1.20.1", "fabric")
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].name, "Sodium")
        self.assertEqual(projects[0].source, "modrinth")
        self.assertIsInstance(projects[0], MarketProject)


if __name__ == "__main__":
    unittest.main()
