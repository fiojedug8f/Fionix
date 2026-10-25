"""Unit tests for the settings persistence layer (no Qt required)."""

from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from src.core.config_manager import (
    DEFAULT_MEMORY_MB,
    ConfigManager,
)


class ConfigManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        # Use a workspace-local scratch directory instead of the system temp:
        # sandboxed/managed Windows environments often lock the latter down.
        temp_root = Path(__file__).resolve().parent / ".tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.data_dir = temp_root / f"case-{uuid.uuid4().hex}" / "Fionix"

    def tearDown(self) -> None:
        shutil.rmtree(self.data_dir.parent, ignore_errors=True)

    def test_first_run_creates_layout_and_defaults(self) -> None:
        config = ConfigManager(self.data_dir)

        self.assertTrue(config.first_run)
        self.assertTrue(config.config_path.is_file())
        self.assertTrue(config.instances_dir.is_dir())
        self.assertTrue((config.data_dir / "logs").is_dir())
        self.assertEqual(config.theme, "dark")
        self.assertEqual(config.memory_mb, DEFAULT_MEMORY_MB)
        self.assertEqual(config.last_page, "home")

        payload = json.loads(config.config_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 2)
        self.assertIn("window", payload)
        self.assertIn("background", payload)
        self.assertIn("premium", payload)

    def test_values_roundtrip(self) -> None:
        config = ConfigManager(self.data_dir)
        config.update(
            {
                "theme": "midnight",
                "memory_mb": 8192,
                "last_page": "settings",
                "accent": "#22C55E",
                "proxy": {
                    "enabled": True,
                    "host": "127.0.0.1",
                    "port": 1080,
                    "username": "steve",
                    "password": "secret",
                },
                "curseforge_key": "cf-key",
                "instances_path": "D:/FionixInstances",
                "background": {"mode": "image", "path": "D:/bg.png"},
                "premium": {"key": "dodo-key", "active": True},
                "java": {"path": "C:/Java/bin/java.exe", "auto": False},
            }
        )

        reloaded = ConfigManager(self.data_dir)
        self.assertFalse(reloaded.first_run)
        self.assertEqual(reloaded.theme, "midnight")
        self.assertEqual(reloaded.memory_mb, 8192)
        self.assertEqual(reloaded.last_page, "settings")
        proxy = reloaded.get("proxy")
        self.assertTrue(proxy["enabled"])
        self.assertEqual(proxy["host"], "127.0.0.1")
        self.assertEqual(proxy["port"], 1080)
        self.assertEqual(proxy["password"], "secret")
        self.assertEqual(reloaded.accent, "#22c55e")
        self.assertEqual(reloaded.instances_path, "D:/FionixInstances")
        self.assertEqual(reloaded.get("curseforge_key"), "cf-key")
        self.assertTrue(reloaded.premium_active)
        self.assertEqual(reloaded.get("background")["mode"], "image")
        self.assertEqual(reloaded.get("java")["path"], "C:/Java/bin/java.exe")

    def test_invalid_values_are_sanitised(self) -> None:
        self.data_dir.mkdir(parents=True)
        (self.data_dir / "config.json").write_text(
            json.dumps(
                {
                    "theme": "neon-rainbow",
                    "memory_mb": -12,
                    "last_page": "../../etc/passwd",
                    "accent": "not-a-colour",
                    "proxy": {"enabled": "yes", "port": 999999},
                    "background": {"mode": "weird", "path": 42},
                    "window": {"width": 200, "height": "huge", "x": "left"},
                }
            ),
            encoding="utf-8",
        )

        config = ConfigManager(self.data_dir)
        self.assertEqual(config.theme, "dark")
        self.assertGreaterEqual(config.memory_mb, 1024)
        self.assertLessEqual(config.memory_mb, 16384)
        self.assertEqual(config.last_page, "home")
        self.assertIs(config.get("proxy")["enabled"], False)
        self.assertEqual(config.get("proxy")["port"], 65535)
        self.assertEqual(config.get("window")["width"], 1024)
        self.assertIsNone(config.get("window")["x"])
        self.assertEqual(config.accent, "")
        self.assertEqual(config.get("background")["mode"], "asset")

    def test_corrupt_json_is_backed_up(self) -> None:
        self.data_dir.mkdir(parents=True)
        broken = self.data_dir / "config.json"
        broken.write_text("{ definitely not json", encoding="utf-8")

        config = ConfigManager(self.data_dir)

        backups = list(self.data_dir.glob("config.invalid-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "{ definitely not json")
        self.assertEqual(config.theme, "dark")
        self.assertTrue(broken.is_file())
        json.loads(broken.read_text(encoding="utf-8"))

    def test_window_state_and_reset(self) -> None:
        config = ConfigManager(self.data_dir)
        config.set_window_state(1500, 900, 100, 80, maximized=True)

        window = config.get("window")
        self.assertEqual((window["width"], window["height"]), (1500, 900))
        self.assertEqual((window["x"], window["y"]), (100, 80))
        self.assertTrue(window["maximized"])

        self.assertTrue(config.reset())
        reloaded = ConfigManager(self.data_dir)
        self.assertEqual(reloaded.theme, "dark")
        self.assertFalse(reloaded.get("window")["maximized"])
        self.assertEqual(reloaded.get("player")["name"], "Гость")


if __name__ == "__main__":
    unittest.main()
