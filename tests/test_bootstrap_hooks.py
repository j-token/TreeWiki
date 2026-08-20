from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "treewiki" / "scripts"


class BootstrapHookTests(unittest.TestCase):
    PRINCIPAL = "user:owner"
    TEAM = "team:repository"

    def _initialize_repository(
        self,
        repository: Path,
        *,
        version: int = 5,
        capture: str = "explicit",
        managers: list[str] | None = None,
    ) -> None:
        config_path = repository / ".knowledge" / "config.yml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            yaml.safe_dump(
                {
                    "version": version,
                    "memory": {
                        "layout_version": 2,
                        "capture": capture,
                    },
                    "access_control": {
                        "managers": managers or [self.PRINCIPAL],
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def _installer_command(
        self,
        codex_home: Path,
        repository: Path,
        *,
        apply: bool = True,
        approve_global: bool = True,
        principal: str | None = None,
    ) -> list[str]:
        command = [
            sys.executable,
            str(SCRIPTS / "install_treewiki_hooks.py"),
            "--codex-home",
            str(codex_home),
            "--repository",
            str(repository),
            "--principal",
            principal or self.PRINCIPAL,
            "--team",
            self.TEAM,
        ]
        if apply:
            command.append("--apply")
        if approve_global:
            command.append("--approve-global-hook-apply")
        return command

    def _write_owned_hook(self, codex_home: Path) -> Path:
        codex_home.mkdir(parents=True, exist_ok=True)
        hooks_path = codex_home / "hooks.json"
        hooks_path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "python lmwiki_hook.py",
                                    }
                                ]
                            }
                        ]
                    }
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return hooks_path

    def test_bootstrap_prepares_repository_hook_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "bootstrap_treewiki.py"),
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
            self.assertEqual(config["memory"]["capture"], "explicit")
            self.assertFalse(config["hooks"]["enabled"])
            self.assertEqual(config["hooks"]["runbook"]["status"], "draft")
            self.assertTrue(config["hooks"]["runbook"]["require_user_confirmation"])
            self.assertEqual(config["glossary_path"], "docs/vocabulary/glossary.yml")
            glossary = yaml.safe_load(
                (repository / "docs" / "vocabulary" / "glossary.yml").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(glossary["terms"][0]["term"], "용어집")

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
            self._initialize_repository(fallback)
            hooks_dir = codex_home / "hooks"
            hooks_dir.mkdir(parents=True)
            original = {
                "custom": {"preserved": True},
                "hooks": {
                    event: [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'python "C:/old/lmwiki_hook.py"',
                                    "timeout": timeout,
                                }
                            ]
                        }
                    ]
                    for event, timeout in {
                        "SessionStart": 10,
                        "UserPromptSubmit": 10,
                        "Stop": 30,
                        "SessionEnd": 3,
                    }.items()
                },
            }
            original["hooks"]["Stop"][0]["hooks"].append(
                {"type": "command", "command": "python unrelated.py", "timeout": 5}
            )
            (codex_home / "hooks.json").write_text(
                json.dumps(original, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (hooks_dir / "lmwiki_hook.py").write_text("# preserved legacy runner\n", encoding="utf-8")
            (hooks_dir / "lmwiki-global.json").write_text(
                json.dumps({"fallback_repository": str(fallback.resolve())}) + "\n",
                encoding="utf-8",
            )
            command = self._installer_command(codex_home, fallback)
            for attempt in range(2):
                result = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                if attempt == 0:
                    self.assertIn("legacy LMWiki hook registration detected", result.stderr)
                else:
                    self.assertEqual(result.stderr, "")
            hooks = json.loads(
                (codex_home / "hooks.json").read_text(encoding="utf-8")
            )
            self.assertEqual(hooks["custom"], {"preserved": True})
            self.assertEqual(
                set(hooks["hooks"]),
                {"SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"},
            )
            for groups in hooks["hooks"].values():
                matches = [
                    hook
                    for group in groups
                    for hook in group["hooks"]
                    if "treewiki_hook.py" in hook.get("command", "")
                ]
                self.assertEqual(len(matches), 1)
                self.assertNotIn("python3", matches[0]["command"])
                self.assertFalse(
                    any(
                        "lmwiki_hook.py" in hook.get("command", "")
                        for group in groups
                        for hook in group["hooks"]
                    )
                )
            self.assertTrue((hooks_dir / "treewiki_hook.py").is_file())
            self.assertEqual(
                (hooks_dir / "lmwiki_hook.py").read_text(encoding="utf-8"),
                "# preserved legacy runner\n",
            )
            settings = json.loads(
                (hooks_dir / "treewiki-global.json").read_text(encoding="utf-8")
            )
            self.assertEqual(settings["schema"], "treewiki.hook-settings/v1")
            self.assertEqual(Path(settings["fallback_repository"]), fallback.resolve())
            self.assertTrue((codex_home / "hooks.json.treewiki-backup").is_file())
            self.assertTrue((hooks_dir / "lmwiki-global.json.treewiki-backup").is_file())
            self.assertFalse(any(codex_home.rglob("*.treewiki-tmp")))
            self.assertFalse(any(codex_home.rglob("*.lmwiki-tmp")))

    def test_standalone_installer_defaults_to_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "wiki"
            codex_home = base / "codex-home"
            self._initialize_repository(repository)
            hooks_path = self._write_owned_hook(codex_home)
            before = hooks_path.read_bytes()

            result = subprocess.run(
                self._installer_command(
                    codex_home,
                    repository,
                    apply=False,
                    approve_global=False,
                ),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("DRY-RUN", result.stdout)
            self.assertEqual(hooks_path.read_bytes(), before)
            self.assertFalse((codex_home / "hooks" / "treewiki_hook.py").exists())

    def test_standalone_installer_requires_global_apply_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "wiki"
            codex_home = base / "codex-home"
            self._initialize_repository(repository)
            hooks_path = self._write_owned_hook(codex_home)
            before = hooks_path.read_bytes()

            result = subprocess.run(
                self._installer_command(
                    codex_home,
                    repository,
                    apply=True,
                    approve_global=False,
                ),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("--approve-global-hook-apply", result.stderr)
            self.assertEqual(hooks_path.read_bytes(), before)
            self.assertFalse((codex_home / "hooks" / "treewiki_hook.py").exists())

    def test_standalone_installer_enforces_repository_contract_and_manager(self) -> None:
        cases = [
            ({"version": 2}, "config version 5"),
            ({"capture": "automatic"}, "memory.capture: explicit"),
            ({"managers": ["user:someone-else"]}, "management denied"),
        ]
        for overrides, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                with tempfile.TemporaryDirectory() as temporary:
                    base = Path(temporary)
                    repository = base / "wiki"
                    codex_home = base / "codex-home"
                    self._initialize_repository(
                        repository,
                        version=overrides.get("version", 5),
                        capture=overrides.get("capture", "explicit"),
                        managers=overrides.get("managers", [self.PRINCIPAL]),
                    )
                    hooks_path = self._write_owned_hook(codex_home)
                    before = hooks_path.read_bytes()

                    result = subprocess.run(
                        self._installer_command(codex_home, repository),
                        check=False,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                    )

                    self.assertEqual(result.returncode, 1)
                    self.assertIn(expected_error, result.stderr)
                    self.assertEqual(hooks_path.read_bytes(), before)
                    self.assertFalse(
                        (codex_home / "hooks" / "treewiki_hook.py").exists()
                    )

    def test_standalone_installer_rejects_a_different_fallback_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "wiki"
            other = base / "other"
            codex_home = base / "codex-home"
            self._initialize_repository(repository)
            self._initialize_repository(other)
            hooks_path = self._write_owned_hook(codex_home)
            before = hooks_path.read_bytes()
            command = self._installer_command(codex_home, repository)
            command.extend(["--fallback-repository", str(other)])

            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("must match the authorized --repository", result.stderr)
            self.assertEqual(hooks_path.read_bytes(), before)
            self.assertFalse((codex_home / "hooks" / "treewiki_hook.py").exists())

    def test_global_installer_does_not_enable_an_unregistered_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            codex_home = base / "codex-home"
            repository = base / "wiki"
            self._initialize_repository(repository)
            codex_home.mkdir()
            original = {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {"type": "command", "command": "python unrelated.py"}
                            ]
                        }
                    ]
                }
            }
            hooks_path = codex_home / "hooks.json"
            hooks_path.write_text(
                json.dumps(original, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            before = hooks_path.read_bytes()
            result = subprocess.run(
                self._installer_command(codex_home, repository),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(hooks_path.read_bytes(), before)
            self.assertFalse((codex_home / "hooks" / "treewiki_hook.py").exists())
            self.assertFalse((codex_home / "hooks.json.treewiki-backup").exists())

    def test_global_installer_consolidates_owned_duplicates_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            codex_home = base / "codex-home"
            repository = base / "wiki"
            self._initialize_repository(repository)
            codex_home.mkdir()
            hooks = {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {"type": "command", "command": "python lmwiki_hook.py"},
                                {"type": "command", "command": "python keep.py"},
                            ]
                        },
                        {
                            "hooks": [
                                {"type": "command", "command": "python treewiki_hook.py"}
                            ]
                        },
                    ]
                }
            }
            (codex_home / "hooks.json").write_text(
                json.dumps(hooks) + "\n", encoding="utf-8"
            )
            result = subprocess.run(
                self._installer_command(codex_home, repository),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
            commands = [
                hook["command"]
                for group in installed["hooks"]["Stop"]
                for hook in group["hooks"]
            ]
            self.assertEqual(sum("treewiki_hook.py" in value for value in commands), 1)
            self.assertEqual(sum("lmwiki_hook.py" in value for value in commands), 0)
            self.assertEqual(sum("keep.py" in value for value in commands), 1)

    def test_global_installer_rejects_malformed_hooks_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            codex_home = base / "codex-home"
            repository = base / "wiki"
            self._initialize_repository(repository)
            codex_home.mkdir()
            hooks_path = codex_home / "hooks.json"
            malformed = '{"hooks":{"Stop":[{"hooks":"not-an-array"}]}}\n'
            hooks_path.write_text(malformed, encoding="utf-8")
            result = subprocess.run(
                self._installer_command(codex_home, repository),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("must contain a hooks array", result.stderr)
            self.assertEqual(hooks_path.read_text(encoding="utf-8"), malformed)
            self.assertFalse((codex_home / "hooks.json.treewiki-backup").exists())

    def test_invalid_treewiki_settings_block_legacy_fallback_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            codex_home = base / "codex-home"
            hooks_dir = codex_home / "hooks"
            fallback = base / "wiki"
            hooks_dir.mkdir(parents=True)
            self._initialize_repository(fallback)
            hooks_path = codex_home / "hooks.json"
            hooks_path.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "Stop": [
                                {
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "python lmwiki_hook.py",
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            before = hooks_path.read_bytes()
            (hooks_dir / "treewiki-global.json").write_text("{}\n", encoding="utf-8")
            (hooks_dir / "lmwiki-global.json").write_text(
                json.dumps({"fallback_repository": str(fallback.resolve())}) + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                self._installer_command(codex_home, fallback),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("TreeWiki hook settings schema", result.stderr)
            self.assertEqual(hooks_path.read_bytes(), before)
            self.assertFalse((hooks_dir / "treewiki_hook.py").exists())
            self.assertFalse((codex_home / "hooks.json.treewiki-backup").exists())


if __name__ == "__main__":
    unittest.main()
