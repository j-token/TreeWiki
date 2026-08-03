from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "lmwiki" / "scripts"


class BootstrapHookTests(unittest.TestCase):
    def test_bootstrap_prepares_repository_hook_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "bootstrap_lmwiki.py"),
                    str(repository),
                    "--embedding",
                    "disabled",
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((repository / ".codex" / "hooks.json").exists())
            self.assertTrue(
                (repository / ".knowledge" / "hooks" / "state" / ".gitignore").is_file()
            )
            config = yaml.safe_load(
                (repository / ".knowledge" / "config.yml").read_text(encoding="utf-8")
            )
            self.assertEqual(config["memory"]["capture"], "hook")
            self.assertEqual(config["hooks"]["runbook"]["status"], "draft")

            validation = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "knowledge_cli.py"),
                    "manage",
                    "validate",
                    str(repository),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)
            self.assertIn("0 errors, 0 warnings", validation.stdout)

    def test_global_installer_merges_hooks_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            codex_home = base / "codex-home"
            fallback = base / "wiki"
            (fallback / ".knowledge").mkdir(parents=True)
            (fallback / ".knowledge" / "config.yml").write_text("version: 1\n", encoding="utf-8")
            command = [
                sys.executable,
                str(SCRIPTS / "install_global_hooks.py"),
                "--codex-home",
                str(codex_home),
                "--fallback-repository",
                str(fallback),
            ]
            for _ in range(2):
                result = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            hooks = json.loads(
                (codex_home / "hooks.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                set(hooks["hooks"]),
                {"SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"},
            )
            for groups in hooks["hooks"].values():
                matches = [
                    hook
                    for group in groups
                    for hook in group["hooks"]
                    if "lmwiki_hook.py" in hook["command"]
                ]
                self.assertEqual(len(matches), 1)
                self.assertNotIn("python3", matches[0]["command"])
            self.assertTrue((codex_home / "hooks" / "lmwiki_hook.py").is_file())
            settings = json.loads(
                (codex_home / "hooks" / "lmwiki-global.json").read_text(encoding="utf-8")
            )
            self.assertEqual(Path(settings["fallback_repository"]), fallback.resolve())


if __name__ == "__main__":
    unittest.main()
