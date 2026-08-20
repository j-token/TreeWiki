from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "skills" / "treewiki" / "scripts" / "bootstrap_treewiki.py"


class BootstrapMemoryLayoutTests(unittest.TestCase):
    def bootstrap(self, repository: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(BOOTSTRAP), str(repository), "--embedding", "disabled"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_fresh_bootstrap_uses_v5_local_history_and_typed_shared_l3(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            result = self.bootstrap(repository)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            config = yaml.safe_load(
                (repository / ".knowledge" / "config.yml").read_text(encoding="utf-8")
            )
            self.assertEqual(config["version"], 5)
            self.assertEqual(config["memory"]["layout_version"], 2)
            self.assertEqual(config["memory"]["private_path"], ".knowledge/private-memory")
            self.assertEqual(config["memory"]["shared_path"], "docs/memory")
            self.assertIn(".knowledge/private-memory/l0/**/*.md", config["documents"]["include"])
            self.assertNotIn(".knowledge/private-memory/**/*.md", config["documents"]["include"])

            self.assertTrue((repository / ".knowledge" / "private-memory" / "l0").is_dir())
            for level in ("l1", "l2", "l3"):
                self.assertFalse((repository / ".knowledge" / "private-memory" / level).exists())
                self.assertTrue((repository / "docs" / "memory" / level).is_dir())
            self.assertTrue((repository / "docs" / "memory" / "l3" / "knowledge").is_dir())
            self.assertTrue((repository / "docs" / "memory" / "l3" / "persona").is_dir())
            self.assertEqual(config["history"]["enforce"], True)
            self.assertTrue((repository / ".knowledge" / "document-history" / "MAP-ROOT-001.jsonl").is_file())
            self.assertFalse((repository / "MAP-ROOT-001.history.jsonl").exists())
            self.assertEqual(
                (repository / ".knowledge" / "private-memory" / ".gitignore").read_text(
                    encoding="utf-8"
                ),
                "/l0/\n",
            )
            self.assertEqual(
                (repository / ".knowledge" / ".gitignore").read_text(encoding="utf-8"),
                "/upgrade-backups/\n/document-backups/\n/document-history/\n",
            )
            self.assertEqual(
                (repository / ".agents" / "skills" / ".gitignore").read_text(
                    encoding="utf-8"
                ),
                "/.treewiki-backups/\n",
            )

    def test_repeated_bootstrap_preserves_the_v5_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            first = self.bootstrap(repository)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            config_path = repository / ".knowledge" / "config.yml"
            before = config_path.read_text(encoding="utf-8")

            second = self.bootstrap(repository)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("SKIPPED", second.stdout)
            self.assertEqual(config_path.read_text(encoding="utf-8"), before)

    def test_bootstrap_finalizes_only_documents_created_by_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            unmanaged = repository / "docs" / "notes.md"
            unmanaged.parent.mkdir(parents=True)
            unmanaged.write_text("# Existing untyped notes\n", encoding="utf-8")

            result = self.bootstrap(repository)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(unmanaged.read_text(encoding="utf-8"), "# Existing untyped notes\n")
            self.assertTrue((repository / ".knowledge" / "document-history" / "MAP-ROOT-001.jsonl").is_file())

    def test_git_ignores_only_l0_and_transaction_backups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            result = self.bootstrap(repository)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
            candidates = {
                "l0": repository / ".knowledge" / "private-memory" / "l0" / "raw.md",
                "transaction": repository / ".knowledge" / "upgrade-backups" / "tx" / "record",
                "skill_backup": repository / ".agents" / "skills" / ".treewiki-backups" / "tx" / "skill",
                "l1": repository / "docs" / "memory" / "l1" / "shared.md",
                "l2": repository / "docs" / "memory" / "l2" / "shared.md",
                "l3": repository / "docs" / "memory" / "l3" / "shared.md",
            }
            for path in candidates.values():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture\n", encoding="utf-8")
            for name in ("l0", "transaction", "skill_backup"):
                ignored = subprocess.run(
                    ["git", "-C", str(repository), "check-ignore", "--quiet", str(candidates[name])],
                    check=False,
                )
                self.assertEqual(ignored.returncode, 0, name)
            for name in ("l1", "l2", "l3"):
                tracked = subprocess.run(
                    ["git", "-C", str(repository), "check-ignore", "--quiet", str(candidates[name])],
                    check=False,
                )
                self.assertEqual(tracked.returncode, 1, name)

    def test_legacy_v2_requires_an_explicit_upgrade_without_writing_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            config_path = repository / ".knowledge" / "config.yml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("version: 2\n", encoding="utf-8")

            result = self.bootstrap(repository)
            self.assertEqual(result.returncode, 1)
            self.assertIn("UPGRADE REQUIRED", result.stderr)
            self.assertIn("config version 2", result.stderr)
            self.assertFalse((repository / "docs" / "memory").exists())
            self.assertFalse((repository / ".knowledge" / "private-memory").exists())
            self.assertEqual(config_path.read_text(encoding="utf-8"), "version: 2\n")


if __name__ == "__main__":
    unittest.main()
