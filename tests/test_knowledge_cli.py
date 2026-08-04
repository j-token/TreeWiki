from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills" / "lmwiki" / "scripts" / "knowledge_cli.py"


class KnowledgeCliTests(unittest.TestCase):
    def write_config(self, root: Path, *, version: int = 1) -> None:
        (root / ".knowledge").mkdir(parents=True, exist_ok=True)
        config = {
            "version": version,
            "documents": {"include": [".knowledge/private-memory/**/*.md"], "exclude": []},
            "memory": {
                "enabled": True,
                "capture": "explicit",
                "private_path": ".knowledge/private-memory",
                "persona_requires_sources": 2,
            },
            "hooks": {"l3": {"enabled": True, "minimum_sources": 2}},
            "access_control": {
                "default_visibility": "team",
                "default_owner": "user:owner",
                "default_team": "team:repo",
                "managers": ["user:owner"],
            },
        }
        (root / ".knowledge" / "config.yml").write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    def write_memory(self, root: Path, index: int) -> None:
        memory_dir = root / ".knowledge" / "private-memory" / "l1"
        memory_dir.mkdir(parents=True, exist_ok=True)
        (memory_dir / f"source-{index}.md").write_text(
            "---\n"
            f"id: MEMORY-L1-TEST-00{index}\n"
            "title: test\ntype: memory\nstatus: active\nauthority: informative\n"
            "topics: [test]\nsummary: test\nrelations: []\nreviewed: 2026-08-04\n"
            "memory:\n  level: l1\n  subject: project:test\n  confidence: 1.0\n"
            "access:\n  visibility: private\n  owner: user:owner\n  team: team:repo\n  grants: []\n"
            "---\n",
            encoding="utf-8",
        )

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_l3_candidates_are_acl_filtered_and_programmatic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root)
            self.write_memory(root, 1)
            self.write_memory(root, 2)
            allowed = self.run_cli(
                "query", "l3-candidates", str(root), "--principal", "user:owner",
                "--team", "team:repo", "--json",
            )
            self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
            self.assertIn('"subject":"project:test"', allowed.stdout)
            self.assertIn('"MEMORY-L1-TEST-001"', allowed.stdout)
            self.assertIn('"MEMORY-L1-TEST-002"', allowed.stdout)
            denied = self.run_cli(
                "query", "l3-candidates", str(root), "--principal", "user:other",
                "--team", "team:repo",
            )
            self.assertEqual(denied.stdout.strip(), "NO ELIGIBLE L3 CANDIDATES")

    def test_migrate_reports_and_applies_config_version_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root)
            identity = ("--principal", "user:owner", "--team", "team:repo")
            plan = self.run_cli("manage", "migrate", str(root), *identity)
            self.assertEqual(plan.returncode, 0, plan.stdout + plan.stderr)
            self.assertIn("CONFIG VERSION 1 -> 2", plan.stdout)
            self.assertEqual(
                yaml.safe_load((root / ".knowledge/config.yml").read_text(encoding="utf-8"))["version"],
                1,
            )
            applied = self.run_cli("manage", "migrate", str(root), "--apply", *identity)
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            self.assertIn("APPLIED migration to config version 2", applied.stdout)
            second = self.run_cli("manage", "migrate", str(root), *identity)
            self.assertIn("CONFIG VERSION 2 -> 2", second.stdout)
            self.assertIn("CONFIG KEYS TO ADD 0", second.stdout)

    def test_migrate_can_sync_repository_skill_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root)
            stale = root / ".agents/skills/lmwiki/SKILL.md"
            stale.parent.mkdir(parents=True)
            stale.write_text("stale\n", encoding="utf-8")
            identity = ("--principal", "user:owner", "--team", "team:repo")
            plan = self.run_cli(
                "manage", "migrate", str(root), "--sync-skill-copy", *identity
            )
            self.assertEqual(plan.returncode, 0, plan.stdout + plan.stderr)
            self.assertEqual(stale.read_text(encoding="utf-8"), "stale\n")
            applied = self.run_cli(
                "manage", "migrate", str(root), "--sync-skill-copy", "--apply", *identity
            )
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            expected = (ROOT / "skills/lmwiki/SKILL.md").read_text(encoding="utf-8")
            self.assertEqual(stale.read_text(encoding="utf-8"), expected)


if __name__ == "__main__":
    unittest.main()
