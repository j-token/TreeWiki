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
        vocabulary_dir = root / "docs" / "vocabulary"
        vocabulary_dir.mkdir(parents=True, exist_ok=True)
        (vocabulary_dir / "topics.yml").write_text(
            "test:\n  label: Test\n  aliases: []\n", encoding="utf-8"
        )
        (vocabulary_dir / "glossary.yml").write_text("terms: []\n", encoding="utf-8")
        config = {
            "version": version,
            "documents": {"include": [".knowledge/private-memory/**/*.md"], "exclude": []},
            "vocabulary_path": "docs/vocabulary/topics.yml",
            "glossary_path": "docs/vocabulary/glossary.yml",
            "memory": {
                "enabled": True,
                "capture": "explicit",
                "private_path": ".knowledge/private-memory",
                "persona_requires_sources": 2,
            },
            "hooks": {"l3": {"enabled": True, "minimum_sources": 2}},
            "embedding": {
                "enabled": True,
                "execution": "local",
                "remote_content_allowed": False,
                "index_path": ".knowledge/index/",
            },
            "retrieval": {
                "bm25_enabled": True,
                "bm25_index_path": ".knowledge/index/search.db",
            },
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

    def write_memory(
        self,
        root: Path,
        index: int,
        subject: str = "project:test",
        *,
        level: str = "l1",
        parent: str | None = None,
        kind: str | None = None,
        provenance: str | None = None,
    ) -> str:
        memory_dir = root / ".knowledge" / "private-memory" / level
        memory_dir.mkdir(parents=True, exist_ok=True)
        doc_id = f"MEMORY-{level.upper()}-TEST-00{index}"
        relations = (
            f"\n  - type: distilled_from\n    target: {parent}" if parent else " []"
        )
        kind_line = f"  kind: {kind}\n" if kind else ""
        provenance_block = (
            f"provenance:\n  - source: {provenance}\n    relation: captured_from\n"
            if provenance
            else ""
        )
        (memory_dir / f"source-{index}.md").write_text(
            "---\n"
            f"id: {doc_id}\n"
            "title: test\ntype: memory\nstatus: active\nauthority: informative\n"
            f"topics: [test]\nsummary: test\nrelations:{relations}\nreviewed: 2026-08-04\n"
            f"memory:\n  level: {level}\n  subject: {subject}\n{kind_line}  confidence: 1.0\n"
            "access:\n  visibility: private\n  owner: user:owner\n  team: team:repo\n  grants: []\n"
            f"{provenance_block}"
            "---\n",
            encoding="utf-8",
        )
        return doc_id

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
            l0_one = self.write_memory(root, 1, level="l0", provenance="conversation:work-1")
            l0_two = self.write_memory(root, 2, level="l0", provenance="conversation:work-2")
            self.write_memory(root, 3, parent=l0_one)
            self.write_memory(root, 4, parent=l0_two)

            allowed = self.run_cli(
                "query",
                "l3-candidates",
                str(root),
                "--principal",
                "user:owner",
                "--team",
                "team:repo",
                "--json",
            )
            self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
            self.assertIn('"subject":"project:test"', allowed.stdout)
            self.assertIn('"MEMORY-L1-TEST-003"', allowed.stdout)
            self.assertIn('"MEMORY-L1-TEST-004"', allowed.stdout)
            self.assertIn('"provenance:conversation:work-1"', allowed.stdout)

            denied = self.run_cli(
                "query",
                "l3-candidates",
                str(root),
                "--principal",
                "user:other",
                "--team",
                "team:repo",
            )
            self.assertEqual(denied.returncode, 0, denied.stdout + denied.stderr)
            self.assertEqual(denied.stdout.strip(), "NO ELIGIBLE L3 CANDIDATES")

    def test_l3_candidates_do_not_count_l1_and_derived_l2_twice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root)
            l0 = self.write_memory(root, 1, level="l0", provenance="conversation:one-work")
            l1 = self.write_memory(root, 2, parent=l0)
            self.write_memory(root, 3, level="l2", parent=l1)
            result = self.run_cli(
                "query", "l3-candidates", str(root),
                "--principal", "user:owner", "--team", "team:repo",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), "NO ELIGIBLE L3 CANDIDATES")

    def test_preferences_are_returned_without_task_search_terms(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root)
            l0 = self.write_memory(root, 1, level="l0", subject="user:owner")
            self.write_memory(
                root, 2, subject="user:owner", parent=l0, kind="conditional-action"
            )
            result = self.run_cli(
                "query", "preferences", str(root),
                "--principal", "user:owner", "--team", "team:repo", "--json",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('"id":"MEMORY-L1-TEST-002"', result.stdout)

    def test_migrate_reports_and_applies_config_version_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root, version=1)
            identity = ("--principal", "user:owner", "--team", "team:repo")

            plan = self.run_cli("manage", "migrate", str(root), *identity)
            self.assertEqual(plan.returncode, 0, plan.stdout + plan.stderr)
            self.assertIn("CONFIG VERSION 1 -> 2", plan.stdout)
            self.assertEqual(
                yaml.safe_load((root / ".knowledge" / "config.yml").read_text(encoding="utf-8"))[
                    "version"
                ],
                1,
            )

            applied = self.run_cli("manage", "migrate", str(root), "--apply", *identity)
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            self.assertIn("APPLIED migration to config version 2", applied.stdout)
            config = yaml.safe_load(
                (root / ".knowledge" / "config.yml").read_text(encoding="utf-8")
            )
            self.assertEqual(config["version"], 2)

            second_plan = self.run_cli("manage", "migrate", str(root), *identity)
            self.assertEqual(second_plan.returncode, 0, second_plan.stdout + second_plan.stderr)
            self.assertIn("CONFIG VERSION 2 -> 2", second_plan.stdout)
            self.assertIn("CONFIG KEYS TO ADD 0", second_plan.stdout)

    def test_migrate_can_sync_repository_skill_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root, version=1)
            stale = root / ".agents" / "skills" / "lmwiki" / "SKILL.md"
            stale.parent.mkdir(parents=True)
            stale.write_text("stale\n", encoding="utf-8")
            identity = ("--principal", "user:owner", "--team", "team:repo")

            plan = self.run_cli(
                "manage", "migrate", str(root), "--sync-skill-copy", *identity
            )
            self.assertEqual(plan.returncode, 0, plan.stdout + plan.stderr)
            self.assertIn("SKILL FILES TO UPDATE", plan.stdout)
            self.assertEqual(stale.read_text(encoding="utf-8"), "stale\n")

            applied = self.run_cli(
                "manage",
                "migrate",
                str(root),
                "--sync-skill-copy",
                "--apply",
                *identity,
            )
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            expected = (ROOT / "skills" / "lmwiki" / "SKILL.md").read_text(encoding="utf-8")
            self.assertEqual(stale.read_text(encoding="utf-8"), expected)

    def test_migrate_can_dry_run_and_sync_global_skill_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repository"
            target = Path(temporary) / ".agents" / "skills" / "lmwiki"
            self.write_config(root, version=2)
            stale = target / "SKILL.md"
            stale.parent.mkdir(parents=True)
            stale.write_text("stale\n", encoding="utf-8")
            identity = ("--principal", "user:owner", "--team", "team:repo")
            options = (
                "--sync-global-skill-copy", "--global-skill-target", str(target)
            )

            plan = self.run_cli("manage", "migrate", str(root), *options, *identity)
            self.assertEqual(plan.returncode, 0, plan.stdout + plan.stderr)
            self.assertIn("GLOBAL SKILL FILES TO UPDATE", plan.stdout)
            self.assertEqual(stale.read_text(encoding="utf-8"), "stale\n")

            applied = self.run_cli(
                "manage", "migrate", str(root), "--apply", *options, *identity
            )
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            expected = (ROOT / "skills" / "lmwiki" / "SKILL.md").read_text(encoding="utf-8")
            self.assertEqual(stale.read_text(encoding="utf-8"), expected)

    def test_memory_finalize_is_dry_run_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root, version=2)
            result = self.run_cli(
                "manage", "memory-finalize", str(root),
                "--principal", "user:owner", "--team", "team:repo",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("MEMORY FINALIZE validate -> rebuild derived indexes", result.stdout)
            self.assertIn("DRY-RUN", result.stdout)

    def test_memory_finalize_apply_validates_and_rebuilds_bm25(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root, version=2)
            self.write_memory(
                root, 1, level="l0", subject="user:owner", provenance="conversation:saved"
            )
            result = self.run_cli(
                "manage", "memory-finalize", str(root), "--apply",
                "--principal", "user:owner", "--team", "team:repo",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Validated 1 documents: 0 errors", result.stdout)
            self.assertTrue((root / ".knowledge" / "index" / "search.db").is_file())


if __name__ == "__main__":
    unittest.main()
