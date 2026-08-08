from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "treewiki" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_release_manifest import build_manifest_data, write_release_manifest
from release_manifest import (
    ManifestErrorCode,
    ManifestValidationError,
    SemVer,
    compare_semver,
    load_manifest,
    parse_manifest,
    verify_payload,
)
from upgrade import (
    UpgradeErrorCode,
    UpgradeException,
    apply_upgrade,
    diagnose_upgrade,
    migrate_config_v3,
)
from install_treewiki_hooks import handler, owned_marker
from memory_policy import lineage_equivalence_digest


def sha(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def write_yaml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )


def make_skill(root: Path, *, release: str = "0.1.0") -> Path:
    root.mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "SKILL.md").write_text("# TreeWiki\n", encoding="utf-8")
    (root / "scripts" / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "scripts" / "treewiki_hook.py").write_text(
        "VALUE = 'treewiki-hook'\n", encoding="utf-8"
    )
    write_release_manifest(root, release=release)
    return root


def config(version: int = 2) -> dict:
    return {
        "version": version,
        "documents": {
            "include": ["AGENTS.md", "docs/**/*.md", ".knowledge/private-memory/**/*.md"],
            "exclude": ["custom/**"],
        },
        "memory": {
            "enabled": True,
            "capture": "explicit",
            "private_path": ".knowledge/private-memory",
            "shared_path": "docs/memory",
        },
        "hooks": {"enabled": False},
        "retrieval": {"bm25_enabled": False},
        "access_control": {"managers": ["user:manager"]},
        "unknown_extension": {"kept": True},
    }


def make_repository(root: Path, *, version: int = 2) -> Path:
    root.mkdir(parents=True)
    write_yaml(root / ".knowledge" / "config.yml", config(version))
    return root


def prepare_backup_ignores(repository: Path) -> None:
    (repository / ".knowledge" / ".gitignore").write_text(
        "/upgrade-backups/\n", encoding="utf-8", newline="\n"
    )
    skill_ignore = repository / ".agents" / "skills" / ".gitignore"
    skill_ignore.parent.mkdir(parents=True, exist_ok=True)
    skill_ignore.write_text("/.treewiki-backups/\n", encoding="utf-8", newline="\n")


class SemVerManifestTests(unittest.TestCase):
    def test_semver_is_strict_and_uses_semver_precedence(self) -> None:
        for invalid in ("1", "1.0", "01.0.0", "1.0.0-01", "v1.0.0", "1.0.0+"):
            with self.subTest(invalid=invalid), self.assertRaises(ManifestValidationError):
                SemVer.parse(invalid)
        self.assertLess(compare_semver("1.0.0-alpha.2", "1.0.0-alpha.10"), 0)
        self.assertLess(compare_semver("1.0.0-alpha", "1.0.0"), 0)
        self.assertEqual(compare_semver("1.0.0+one", "1.0.0+two"), 0)

    def test_manifest_rejects_remove_release_boundary_and_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill = make_skill(Path(temporary) / "skill")
            data = load_manifest(skill / "treewiki-release.yml").to_dict()
            data["compatibility"]["remove_in"] = data["release"]
            with self.assertRaises(ManifestValidationError):
                parse_manifest(data)
            data["compatibility"]["remove_in"] = "0.2.0"
            data["artifacts"]["files"][0]["path"] = "../SKILL.md"
            with self.assertRaises(ManifestValidationError) as caught:
                parse_manifest(data)
            self.assertEqual(caught.exception.code, ManifestErrorCode.PATH_TRAVERSAL)

    def test_manifest_preserves_unknown_fields_and_detects_hash_and_completeness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill = make_skill(Path(temporary) / "skill")
            path = skill / "treewiki-release.yml"
            data = load_manifest(path).to_dict()
            data["future"] = {"preserved": True}
            parsed = parse_manifest(data)
            self.assertTrue(parsed.to_dict()["future"]["preserved"])
            (skill / "SKILL.md").write_text("tampered\n", encoding="utf-8")
            problems = verify_payload(parsed, skill)
            self.assertIn(ManifestErrorCode.HASH_MISMATCH, {item.code for item in problems})
            (skill / "extra.txt").write_text("extra\n", encoding="utf-8")
            problems = verify_payload(parsed, skill)
            self.assertIn(
                ManifestErrorCode.ARTIFACT_LIST_INCOMPLETE,
                {item.code for item in problems},
            )

    def test_builder_failure_does_not_destroy_existing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill = make_skill(Path(temporary) / "skill")
            manifest = skill / "treewiki-release.yml"
            before = manifest.read_bytes()
            with self.assertRaises(ManifestValidationError):
                write_release_manifest(skill, release="01.0.0")
            self.assertEqual(manifest.read_bytes(), before)


class ConfigPlanTests(unittest.TestCase):
    def test_config_v3_preserves_unknowns_and_normalizes_layout(self) -> None:
        source = config(1)
        source["memory"]["capture"] = "hook"
        source["documents"]["include"].extend(
            [
                ".knowledge/private-memory/**",
                ".knowledge\\private-memory\\**\\*.md",
                ".knowledge/private-memory/l2/*.md",
            ]
        )
        target = migrate_config_v3(source)
        self.assertEqual(target["version"], 3)
        self.assertEqual(target["memory"]["layout_version"], 1)
        self.assertEqual(target["memory"]["capture"], "explicit")
        self.assertEqual(target["unknown_extension"], {"kept": True})
        self.assertNotIn(
            ".knowledge/private-memory/**/*.md", target["documents"]["include"]
        )
        self.assertIn(
            ".knowledge/private-memory/l0/**/*.md", target["documents"]["include"]
        )
        self.assertFalse(
            any(
                value.replace("\\", "/").startswith(".knowledge/private-memory/")
                and not value.replace("\\", "/").startswith(
                    ".knowledge/private-memory/l0/"
                )
                for value in target["documents"]["include"]
            )
        )
        self.assertEqual(target["documents"]["exclude"][0], "custom/**")
        self.assertIn("lmwiki/**/assets/AGENTS.md", target["documents"]["exclude"])
        self.assertIn("treewiki/**/assets/AGENTS.md", target["documents"]["exclude"])
        self.assertIn("skills/**/assets/AGENTS.md", target["documents"]["exclude"])
        with self.assertRaises(UpgradeException) as caught:
            migrate_config_v3(config(4))
        self.assertEqual(caught.exception.code, UpgradeErrorCode.INCOMPATIBLE_NEWER)

    def test_plan_id_is_deterministic_and_stale_plan_does_not_mutate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            skill = make_skill(base / "skill")
            repo = make_repository(base / "repo")
            global_copy = base / "global" / "treewiki"
            kwargs = {
                "skill_root": skill,
                "stages": "config",
                "global_skill_root": global_copy,
            }
            first = diagnose_upgrade(repo, **kwargs)
            second = diagnose_upgrade(repo, **kwargs)
            self.assertEqual(first["overall"]["plan_id"], second["overall"]["plan_id"])
            config_path = repo / ".knowledge" / "config.yml"
            changed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            changed["concurrent"] = True
            write_yaml(config_path, changed)
            with self.assertRaises(UpgradeException) as caught:
                apply_upgrade(
                    repo,
                    plan_id=first["overall"]["plan_id"],
                    apply=True,
                    principal="user:manager",
                    **kwargs,
                )
            self.assertEqual(caught.exception.code, UpgradeErrorCode.STALE_PLAN)
            self.assertEqual(yaml.safe_load(config_path.read_text(encoding="utf-8"))["version"], 2)
            self.assertFalse((repo / ".knowledge" / "upgrade-backups").exists())

    def test_config_apply_journals_and_fsyncs_without_deletes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            skill = make_skill(base / "skill")
            repo = make_repository(base / "repo")
            kwargs = {
                "skill_root": skill,
                "stages": "config",
                "global_skill_root": base / "global" / "treewiki",
            }
            report = diagnose_upgrade(repo, **kwargs)
            result = apply_upgrade(
                repo,
                plan_id=report["overall"]["plan_id"],
                apply=True,
                principal="user:manager",
                **kwargs,
            )
            self.assertEqual(result["status"], "APPLIED")
            self.assertEqual(result["deletes"], [])
            current = yaml.safe_load(
                (repo / ".knowledge" / "config.yml").read_text(encoding="utf-8")
            )
            self.assertEqual(current["version"], 3)
            self.assertTrue(current["unknown_extension"]["kept"])
            events = [
                json.loads(line)
                for line in (
                    Path(result["backup_path"]) / "transaction.jsonl"
                ).read_text(encoding="utf-8").splitlines()
            ]
            config_events = [
                event
                for event in events
                if event["action_id"] == "migrate_repository_config_v3"
            ]
            self.assertEqual(
                [event["state"] for event in config_events],
                ["planned", "started", "backup_ready", "completed", "verified"],
            )
            self.assertTrue(config_events[0]["backup"].endswith("config.yml"))


class SkillStageTests(unittest.TestCase):
    def test_embedded_payload_can_install_repository_and_global_copies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            skill = make_skill(base / "skill")
            repo = make_repository(base / "repo", version=3)
            current = config(3)
            current["memory"]["layout_version"] = 1
            write_yaml(repo / ".knowledge" / "config.yml", current)
            repository_copy = repo / ".agents" / "skills" / "treewiki"
            global_copy = base / "global" / "treewiki"
            kwargs = {
                "skill_root": skill,
                "stages": "skill",
                "repository_skill_root": repository_copy,
                "global_skill_root": global_copy,
                "approve_global_skill": True,
            }
            report = diagnose_upgrade(repo, **kwargs)
            self.assertEqual(
                {
                    action["id"]
                    for action in report["actions"]
                    if action.get("kind") != "safety_prerequisite"
                },
                {"copy_repository_treewiki_skill", "copy_global_treewiki_skill"},
            )
            result = apply_upgrade(
                repo,
                plan_id=report["overall"]["plan_id"],
                apply=True,
                principal="user:manager",
                **kwargs,
            )
            self.assertEqual(result["status"], "APPLIED")
            self.assertEqual(verify_payload(load_manifest(repository_copy / "treewiki-release.yml"), repository_copy), [])
            self.assertEqual(verify_payload(load_manifest(global_copy / "treewiki-release.yml"), global_copy), [])

    def test_global_skill_copy_requires_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            skill = make_skill(base / "skill")
            repo = make_repository(base / "repo", version=3)
            current = config(3)
            current["memory"]["layout_version"] = 1
            write_yaml(repo / ".knowledge" / "config.yml", current)
            prepare_backup_ignores(repo)
            global_copy = base / "global" / "treewiki"
            common = {
                "skill_root": skill,
                "stages": "skill",
                "repository_skill_root": skill,
                "global_skill_root": global_copy,
            }
            default = diagnose_upgrade(repo, **common)
            approved = diagnose_upgrade(repo, approve_global_skill=True, **common)
            self.assertNotIn(
                "copy_global_treewiki_skill",
                {action["id"] for action in default["actions"]},
            )
            self.assertIn(
                "--approve-global-skill", " ".join(default["guidance"]["apply"])
            )
            self.assertIn(
                "copy_global_treewiki_skill",
                {action["id"] for action in approved["actions"]},
            )
            self.assertNotEqual(
                default["overall"]["plan_id"], approved["overall"]["plan_id"]
            )

    def test_official_newer_manifest_is_guidance_not_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            skill = make_skill(base / "skill")
            repo = make_repository(base / "repo", version=3)
            current = config(3)
            current["memory"]["layout_version"] = 1
            write_yaml(repo / ".knowledge" / "config.yml", current)
            latest = build_manifest_data(skill, release="0.1.1")
            report = diagnose_upgrade(
                repo,
                skill_root=skill,
                check_latest=True,
                latest_fetcher=lambda: (latest, "v0.1.1"),
                repository_skill_root=skill,
                global_skill_root=skill,
            )
            self.assertFalse(report["overall"]["apply_allowed"])
            self.assertEqual(report["authority"]["kind"], "official")
            self.assertIn("npx skills add", " ".join(report["guidance"]["apply"]))
            self.assertFalse(any(action["stage"] == "skill" for action in report["actions"]))


class MemoryLayoutStageTests(unittest.TestCase):
    def _fixture(self, base: Path) -> tuple[Path, Path, bytes, dict]:
        skill = make_skill(base / "skill")
        repo = make_repository(base / "repo")
        write_yaml(
            repo / "docs" / "vocabulary" / "topics.yml",
            {"test-topic": {"aliases": []}},
        )
        write_yaml(repo / "docs" / "vocabulary" / "glossary.yml", {"terms": []})
        legacy = repo / ".knowledge" / "private-memory" / "l1" / "legacy.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(
            "---\nid: MEMORY-ONE\naccess:\n  visibility: team\n---\n\nPrivate source body.\n",
            encoding="utf-8",
        )
        rendered = (
            "---\n"
            "id: MEMORY-ONE\n"
            "title: Shared fact\n"
            "type: reference\n"
            "status: active\n"
            "authority: informative\n"
            "topics:\n  - test-topic\n"
            "summary: Approved shared fact.\n"
            "glossary_terms: []\n"
            "relations: []\n"
            "reviewed: 2026-08-08\n"
            "---\n\nShared fact.\n"
        ).encode("utf-8")
        action = {
            "memory_id": "MEMORY-ONE",
            "source_path": str(legacy),
            "target_path": "docs/memory/l1/memory-one.md",
            "level": "l1",
            "body_sha256": sha(b"Shared fact.\n"),
            "expected_file_sha256": sha(rendered),
            "relation_before": [{"type": "distilled_from", "target": "LOCAL-L0"}],
            "relation_after": [],
            "lineage_digest": lineage_equivalence_digest(
                "MEMORY-ONE", sha(b"Shared fact.\n"), "l1", []
            ),
            "metadata": {"secret": "must-not-leak"},
            "body": "Shared fact.",
        }
        return skill, repo, rendered, action

    @staticmethod
    def _planner(action: dict):
        def planner(root, current_config, approved_ids, *, approvals=None):
            return {
                "schema": "treewiki.memory-layout-plan/v1",
                "approved_ids": sorted(approved_ids),
                "actions": [action] if "MEMORY-ONE" in approved_ids else [],
                "aggregate_lineage_digest": sha(b"aggregate"),
            }

        return planner

    @staticmethod
    def _applier(rendered: bytes):
        def applier(plan, stage_root):
            staged = stage_root / "docs" / "memory" / "l1" / "memory-one.md"
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(rendered)
            return [
                {
                    "memory_id": "MEMORY-ONE",
                    "staged_path": staged,
                    "target_path": "docs/memory/l1/memory-one.md",
                    "expected_file_sha256": sha(rendered),
                    "lineage_digest": sha(b"lineage"),
                }
            ]

        return applier

    def test_exact_approval_lineage_plan_and_staged_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            skill, repo, rendered, action = self._fixture(base)
            kwargs = {
                "skill_root": skill,
                "stages": "memory-layout,config",
                "approved_memory_ids": ["MEMORY-ONE"],
                "memory_layout_planner": self._planner(action),
                "repository_skill_root": skill,
                "global_skill_root": skill,
            }
            report = diagnose_upgrade(repo, **kwargs)
            serialized = json.dumps(report, ensure_ascii=False)
            self.assertNotIn("Private source body", serialized)
            self.assertNotIn("must-not-leak", serialized)
            self.assertNotIn(str(action["source_path"]), serialized)
            self.assertEqual(
                [
                    item["stage"]
                    for item in report["actions"]
                    if item.get("kind") != "safety_prerequisite"
                ],
                ["memory-layout", "config"],
            )
            result = apply_upgrade(
                repo,
                plan_id=report["overall"]["plan_id"],
                apply=True,
                principal="user:manager",
                memory_layout_applier=self._applier(rendered),
                **kwargs,
            )
            self.assertEqual(result["status"], "APPLIED")
            self.assertEqual(
                (repo / "docs" / "memory" / "l1" / "memory-one.md").read_bytes(),
                rendered,
            )
            self.assertEqual(
                yaml.safe_load((repo / ".knowledge" / "config.yml").read_text(encoding="utf-8"))["version"],
                3,
            )
            memory_map = (
                Path(result["backup_path"]) / "memory-map.json"
            ).read_text(encoding="utf-8")
            self.assertNotIn("source_path", memory_map)
            self.assertNotIn("body", memory_map)

    def test_status_approval_targets_keep_plan_id_stable_for_exact_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            skill = make_skill(base / "skill")
            repo = make_repository(base / "repo")
            legacy = repo / ".knowledge" / "private-memory" / "l1" / "eligible.md"
            legacy.parent.mkdir(parents=True)
            metadata = {
                "id": "MEMORY-ELIGIBLE",
                "type": "memory",
                "status": "active",
                "relations": [],
                "memory": {
                    "level": "l1",
                    "subject": "user:owner",
                    "scope": "personal",
                    "kind": "conditional-action",
                    "claim_key": "workflow.example",
                    "claim_value": "enabled",
                    "confidence": 1.0,
                },
                "sharing": {
                    "authored_by": "agent:treewiki",
                    "shared_by": ["user:owner"],
                    "shared_at": "2026-08-08T00:00:00Z",
                    "approved_by": ["user:owner"],
                    "approved_at": "2026-08-08T00:00:00Z",
                    "evidence_digest": "sha256:" + "0" * 64,
                    "source_ref": "local-memory:eligible",
                    "source_hash": "sha256:" + "0" * 64,
                    "source_machine": "install:opaque",
                    "work_unit_id": "work:eligible",
                },
                "access": {
                    "visibility": "team",
                    "owner": "user:owner",
                    "team": "team:repository",
                    "grants": [],
                },
            }
            legacy.write_text(
                "---\n"
                + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
                + "---\n\nEligible body.\n",
                encoding="utf-8",
            )

            def legacy_cli_shell(root, current_config, approved_ids, *, approvals=None):
                return {
                    "schema": "treewiki.memory-layout-plan/v1",
                    "approved_ids": [],
                    "actions": [],
                    "aggregate_lineage_digest": sha(b"[]"),
                }

            common = {
                "skill_root": skill,
                "stages": "memory-layout,config",
                "repository_skill_root": skill,
                "global_skill_root": skill,
            }
            status = diagnose_upgrade(
                repo, memory_layout_planner=legacy_cli_shell, **common
            )
            memory = next(item for item in status["components"] if item["id"] == "memory_layout")
            self.assertEqual(memory["approval_targets"], ["MEMORY-ELIGIBLE"])
            self.assertEqual(memory["dispositions"][0]["disposition"], "share")
            self.assertFalse(status["overall"]["apply_allowed"])
            approved = diagnose_upgrade(
                repo, approved_memory_ids=["MEMORY-ELIGIBLE"], **common
            )
            self.assertEqual(status["overall"]["plan_id"], approved["overall"]["plan_id"])
            self.assertTrue(approved["overall"]["apply_allowed"])

    def test_config_v3_can_preserve_blocked_sensitive_legacy_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            skill = make_skill(base / "skill")
            repo = make_repository(base / "repo")
            legacy = repo / ".knowledge" / "private-memory" / "l1" / "private.md"
            legacy.parent.mkdir(parents=True)
            legacy.write_text(
                "---\n"
                "id: MEMORY-PRIVATE\n"
                "type: memory\n"
                "status: active\n"
                "memory:\n  level: l1\n  subject: old-task-slug\n"
                "access:\n  visibility: private\n  owner: user:manager\n"
                "  team: team:repository\n  grants: []\n"
                "relations: []\n"
                "---\n\nPrivate body.\n",
                encoding="utf-8",
            )
            before = legacy.read_bytes()
            kwargs = {
                "skill_root": skill,
                "stages": "memory-layout,config",
                "repository_skill_root": skill,
                "global_skill_root": skill,
            }
            report = diagnose_upgrade(repo, **kwargs)
            memory = next(
                item for item in report["components"] if item["id"] == "memory_layout"
            )
            self.assertEqual(memory["approval_targets"], [])
            self.assertEqual(memory["dispositions"][0]["disposition"], "blocked_sensitive")
            self.assertEqual(
                [
                    action["id"]
                    for action in report["actions"]
                    if action.get("kind") != "safety_prerequisite"
                ],
                ["migrate_repository_config_v3"],
            )
            self.assertTrue(report["overall"]["apply_allowed"])

            result = apply_upgrade(
                repo,
                plan_id=report["overall"]["plan_id"],
                apply=True,
                principal="user:manager",
                **kwargs,
            )
            self.assertEqual(result["status"], "APPLIED")
            self.assertEqual(legacy.read_bytes(), before)
            self.assertEqual(
                yaml.safe_load(
                    (repo / ".knowledge" / "config.yml").read_text(encoding="utf-8")
                )["version"],
                3,
            )

    def test_memory_target_conflict_blocks_all_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            skill, repo, _rendered, action = self._fixture(base)
            target = repo / "docs" / "memory" / "l1" / "memory-one.md"
            target.parent.mkdir(parents=True)
            target.write_text("conflict\n", encoding="utf-8")
            report = diagnose_upgrade(
                repo,
                skill_root=skill,
                stages="memory-layout,config",
                approved_memory_ids=["MEMORY-ONE"],
                memory_layout_planner=self._planner(action),
                repository_skill_root=skill,
                global_skill_root=skill,
            )
            self.assertEqual(report["overall"]["status"], "blocked")
            self.assertFalse(report["overall"]["apply_allowed"])
            self.assertIn("MEMORY_TARGET_CONFLICT", {error["code"] for error in report["errors"]})

    def test_memory_failure_stops_before_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            skill, repo, rendered, action = self._fixture(base)
            kwargs = {
                "skill_root": skill,
                "stages": "memory-layout,config",
                "approved_memory_ids": ["MEMORY-ONE"],
                "memory_layout_planner": self._planner(action),
                "repository_skill_root": skill,
                "global_skill_root": skill,
            }
            report = diagnose_upgrade(repo, **kwargs)

            def fail(phase, current_action):
                if phase == "stage" and current_action["stage"] == "memory-layout":
                    raise RuntimeError("injected")

            with self.assertRaises(UpgradeException) as caught:
                apply_upgrade(
                    repo,
                    plan_id=report["overall"]["plan_id"],
                    apply=True,
                    principal="user:manager",
                    memory_layout_applier=self._applier(rendered),
                    fault_injector=fail,
                    **kwargs,
                )
            self.assertEqual(caught.exception.code, UpgradeErrorCode.APPLY_FAILED)
            self.assertEqual(
                yaml.safe_load((repo / ".knowledge" / "config.yml").read_text(encoding="utf-8"))["version"],
                2,
            )
            self.assertFalse((repo / "docs" / "memory" / "l1" / "memory-one.md").exists())


class IndexStageTests(unittest.TestCase):
    def _fixture(self, base: Path) -> tuple[Path, Path, Path]:
        skill = make_skill(base / "skill")
        for name in (
            "build_search_index.py",
            "validate_knowledge.py",
            "memory_policy.py",
        ):
            (skill / "scripts" / name).write_bytes((SCRIPTS / name).read_bytes())
        write_release_manifest(skill, release="0.1.0")

        repo = make_repository(base / "repo", version=3)
        current = config(3)
        current["documents"] = {"include": ["docs/**/*.md"], "exclude": []}
        current["memory"]["layout_version"] = 1
        current["retrieval"] = {
            "bm25_enabled": True,
            "bm25_index_path": ".knowledge/index/search.db",
            "bm25_query_mode": "high_recall",
            "result_content": "locations_only",
        }
        current["embedding"] = {"enabled": True, "execution": "local"}
        current = migrate_config_v3(current)
        write_yaml(repo / ".knowledge" / "config.yml", current)
        document = repo / "docs" / "note.md"
        document.parent.mkdir(parents=True)
        document.write_text(
            "---\nid: DOC-INDEX-001\ntitle: Index fixture\ntype: reference\n"
            "status: active\nauthority: informative\ntopics: [test-index]\n"
            "summary: Search index transaction fixture.\nrelations: []\n"
            "reviewed: 2026-08-08\n"
            "embedding:\n  mode: local_only\n  content: full\n---\n\n# First\n\nalpha\n",
            encoding="utf-8",
            newline="\n",
        )
        write_yaml(
            repo / "docs" / "vocabulary" / "topics.yml",
            {"test-index": {"label": "Test index", "aliases": []}},
        )
        write_yaml(repo / "docs" / "vocabulary" / "glossary.yml", {"terms": []})
        prepare_backup_ignores(repo)
        return skill, repo, document

    @staticmethod
    def _kwargs(skill: Path) -> dict:
        return {
            "skill_root": skill,
            "stages": "index",
            "repository_skill_root": skill,
            "global_skill_root": skill,
        }

    def test_missing_apply_current_then_content_stale_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill, repo, document = self._fixture(Path(temporary))
            kwargs = self._kwargs(skill)

            missing = diagnose_upgrade(repo, **kwargs)
            component = next(
                item for item in missing["components"] if item["id"] == "search_index"
            )
            self.assertEqual(component["status"], "missing")
            self.assertEqual(
                [action["id"] for action in missing["actions"]],
                ["rebuild_search_index"],
            )
            result = apply_upgrade(
                repo,
                plan_id=missing["overall"]["plan_id"],
                apply=True,
                principal="user:manager",
                **kwargs,
            )
            self.assertIn("rebuild_search_index", result["completed_actions"])
            database = repo / ".knowledge" / "index" / "search.db"
            self.assertTrue(database.is_file())

            current = diagnose_upgrade(repo, **kwargs)
            component = next(
                item for item in current["components"] if item["id"] == "search_index"
            )
            self.assertEqual(component["status"], "current")
            self.assertFalse(
                any(action["id"] == "rebuild_search_index" for action in current["actions"])
            )

            document.write_text(
                document.read_text(encoding="utf-8").replace("alpha", "beta"),
                encoding="utf-8",
                newline="\n",
            )
            stale = diagnose_upgrade(repo, **kwargs)
            component = next(
                item for item in stale["components"] if item["id"] == "search_index"
            )
            self.assertEqual(component["status"], "upgrade_required")
            second = apply_upgrade(
                repo,
                plan_id=stale["overall"]["plan_id"],
                apply=True,
                principal="user:manager",
                **kwargs,
            )
            self.assertIn("rebuild_search_index", second["completed_actions"])
            self.assertEqual(
                next(
                    item
                    for item in diagnose_upgrade(repo, **kwargs)["components"]
                    if item["id"] == "search_index"
                )["status"],
                "current",
            )

            builder = skill / "scripts" / "build_search_index.py"
            builder.write_text(
                builder.read_text(encoding="utf-8")
                + "\n# builder-contract-regression\n",
                encoding="utf-8",
                newline="\n",
            )
            write_release_manifest(skill, release="0.1.0")
            builder_stale = diagnose_upgrade(repo, **kwargs)
            component = next(
                item
                for item in builder_stale["components"]
                if item["id"] == "search_index"
            )
            self.assertEqual(component["status"], "upgrade_required")
            self.assertTrue(
                any(
                    action["id"] == "rebuild_search_index"
                    for action in builder_stale["actions"]
                )
            )
            apply_upgrade(
                repo,
                plan_id=builder_stale["overall"]["plan_id"],
                apply=True,
                principal="user:manager",
                **kwargs,
            )
            self.assertEqual(
                next(
                    item
                    for item in diagnose_upgrade(repo, **kwargs)["components"]
                    if item["id"] == "search_index"
                )["status"],
                "current",
            )

    def test_validation_failure_precedes_all_index_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill, repo, document = self._fixture(Path(temporary))
            kwargs = self._kwargs(skill)
            initial = diagnose_upgrade(repo, **kwargs)
            apply_upgrade(
                repo,
                plan_id=initial["overall"]["plan_id"],
                apply=True,
                principal="user:manager",
                **kwargs,
            )
            database = repo / ".knowledge" / "index" / "search.db"
            database_before = sha(database.read_bytes())
            transactions_root = repo / ".knowledge" / "upgrade-backups"
            prior_transactions = set(transactions_root.iterdir())

            document.write_text(
                document.read_text(encoding="utf-8").replace("alpha", "stale"),
                encoding="utf-8",
                newline="\n",
            )
            (repo / "docs" / "invalid.md").write_text(
                "missing frontmatter\n", encoding="utf-8", newline="\n"
            )
            stale = diagnose_upgrade(repo, **kwargs)
            self.assertTrue(
                any(action["id"] == "rebuild_search_index" for action in stale["actions"])
            )
            with self.assertRaises(UpgradeException) as caught:
                apply_upgrade(
                    repo,
                    plan_id=stale["overall"]["plan_id"],
                    apply=True,
                    principal="user:manager",
                    **kwargs,
                )
            self.assertEqual(caught.exception.code, UpgradeErrorCode.VERIFICATION_FAILED)
            self.assertEqual(sha(database.read_bytes()), database_before)
            failed_transactions = set(transactions_root.iterdir()) - prior_transactions
            self.assertEqual(len(failed_transactions), 1)
            transaction = failed_transactions.pop()
            self.assertFalse((transaction / "index-staging").exists())
            self.assertFalse((transaction / "index").exists())
            events = [
                json.loads(line)
                for line in (transaction / "transaction.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            verification_failures = [
                event
                for event in events
                if event.get("phase") == "verify" and event.get("state") == "failed"
            ]
            self.assertEqual(len(verification_failures), 1)
            self.assertEqual(
                verification_failures[0]["action_id"],
                "pre_index_repository_validation",
            )


class HookStageTests(unittest.TestCase):
    def _fixture(
        self, base: Path, *, capture: str = "explicit", hooks_enabled: bool = True, version: int = 3
    ) -> tuple[Path, Path, Path]:
        skill = make_skill(base / "skill")
        repo = make_repository(base / "repo", version=version)
        current = config(version)
        current["hooks"]["enabled"] = hooks_enabled
        current["memory"]["capture"] = capture
        if version == 3:
            current["memory"]["layout_version"] = 1
        write_yaml(repo / ".knowledge" / "config.yml", current)
        prepare_backup_ignores(repo)
        codex_home = base / "codex"
        return skill, repo, codex_home

    @staticmethod
    def _write_hooks(codex_home: Path, values: list[dict]) -> None:
        codex_home.mkdir(parents=True, exist_ok=True)
        (codex_home / "hooks.json").write_text(
            json.dumps(
                {"hooks": {"UserPromptSubmit": [{"hooks": values}]}},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _kwargs(self, skill: Path, codex_home: Path, stages: str = "hook") -> dict:
        return {
            "skill_root": skill,
            "stages": stages,
            "repository_skill_root": skill,
            "global_skill_root": skill,
            "codex_home": codex_home,
            "approve_global_hook": True,
        }

    def test_global_hook_requires_separate_plan_bound_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill, repo, codex_home = self._fixture(Path(temporary))
            self._write_hooks(
                codex_home, [{"type": "command", "command": "python lmwiki_hook.py"}]
            )
            common = self._kwargs(skill, codex_home)
            common.pop("approve_global_hook")
            unapproved = diagnose_upgrade(repo, **common)
            approved = diagnose_upgrade(repo, approve_global_hook=True, **common)
            self.assertFalse(any(action["stage"] == "hook" for action in unapproved["actions"]))
            self.assertTrue(any(action["stage"] == "hook" for action in approved["actions"]))
            self.assertNotEqual(
                unapproved["overall"]["plan_id"], approved["overall"]["plan_id"]
            )
            with self.assertRaises(UpgradeException) as caught:
                apply_upgrade(
                    repo,
                    plan_id=approved["overall"]["plan_id"],
                    apply=True,
                    principal="user:manager",
                    **common,
                )
            self.assertEqual(caught.exception.code, UpgradeErrorCode.STALE_PLAN)

    def test_none_does_not_create_registration_when_hooks_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill, repo, codex_home = self._fixture(
                Path(temporary), hooks_enabled=False
            )
            report = diagnose_upgrade(repo, **self._kwargs(skill, codex_home))
            hook = next(item for item in report["components"] if item["id"] == "codex_hook")
            self.assertEqual(hook["status"], "disabled")
            self.assertFalse(any(action["stage"] == "hook" for action in report["actions"]))
            self.assertFalse((codex_home / "hooks.json").exists())

    def test_old_registration_and_settings_migrate_without_enabling_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            skill, repo, codex_home = self._fixture(base, hooks_enabled=False)
            unrelated = {"type": "command", "command": "python unrelated.py"}
            old = {"type": "command", "command": "python lmwiki_hook.py"}
            self._write_hooks(codex_home, [unrelated, old])
            hooks_dir = codex_home / "hooks"
            hooks_dir.mkdir()
            (hooks_dir / "lmwiki-global.json").write_text(
                json.dumps({"fallback_repository": str(repo.resolve())}),
                encoding="utf-8",
            )
            kwargs = self._kwargs(skill, codex_home)
            report = diagnose_upgrade(repo, **kwargs)
            result = apply_upgrade(
                repo,
                plan_id=report["overall"]["plan_id"],
                apply=True,
                principal="user:manager",
                **kwargs,
            )
            self.assertEqual(result["status"], "APPLIED")
            payload = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
            values = payload["hooks"]["UserPromptSubmit"][0]["hooks"]
            self.assertEqual(sum(owned_marker(value) is not None for value in values), 1)
            self.assertEqual(values[0], unrelated)
            self.assertEqual(owned_marker(values[1]), "treewiki_hook.py")
            settings = json.loads(
                (hooks_dir / "treewiki-global.json").read_text(encoding="utf-8")
            )
            self.assertEqual(settings["schema"], "treewiki.hook-settings/v1")
            migrated_config = yaml.safe_load(
                (repo / ".knowledge" / "config.yml").read_text(encoding="utf-8")
            )
            self.assertFalse(migrated_config["hooks"]["enabled"])

    def test_new_registration_is_current_when_runner_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill, repo, codex_home = self._fixture(Path(temporary))
            runner = codex_home / "hooks" / "treewiki_hook.py"
            runner.parent.mkdir(parents=True)
            runner.write_bytes((skill / "scripts" / "treewiki_hook.py").read_bytes())
            self._write_hooks(codex_home, [handler(runner.resolve(), 10, "TreeWiki 작업 준비")])
            report = diagnose_upgrade(repo, **self._kwargs(skill, codex_home))
            hook = next(item for item in report["components"] if item["id"] == "codex_hook")
            self.assertEqual(hook["status"], "current")
            self.assertFalse(any(action["stage"] == "hook" for action in report["actions"]))

    def test_duplicate_owned_is_resolvable_and_collapses_to_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill, repo, codex_home = self._fixture(Path(temporary))
            self._write_hooks(
                codex_home,
                [
                    {"type": "command", "command": "python lmwiki_hook.py"},
                    {"type": "command", "command": "python treewiki_hook.py"},
                ],
            )
            kwargs = self._kwargs(skill, codex_home)
            report = diagnose_upgrade(repo, **kwargs)
            hook = next(item for item in report["components"] if item["id"] == "codex_hook")
            self.assertEqual(hook["status"], "conflict")
            self.assertTrue(hook["resolvable"])
            self.assertTrue(report["overall"]["apply_allowed"])
            apply_upgrade(
                repo,
                plan_id=report["overall"]["plan_id"],
                apply=True,
                principal="user:manager",
                **kwargs,
            )
            payload = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
            values = payload["hooks"]["UserPromptSubmit"][0]["hooks"]
            self.assertEqual(sum(owned_marker(value) is not None for value in values), 1)

    def test_malformed_hooks_and_ambiguous_owned_command_block(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill, repo, codex_home = self._fixture(Path(temporary))
            codex_home.mkdir()
            (codex_home / "hooks.json").write_text("{bad", encoding="utf-8")
            report = diagnose_upgrade(repo, **self._kwargs(skill, codex_home))
            self.assertEqual(report["overall"]["status"], "blocked")
            self._write_hooks(
                codex_home,
                [{"type": "command", "command": "python lmwiki_hook.py"}],
            )
            hooks_dir = codex_home / "hooks"
            hooks_dir.mkdir(exist_ok=True)
            (hooks_dir / "treewiki-global.json").write_text("{bad", encoding="utf-8")
            report = diagnose_upgrade(repo, **self._kwargs(skill, codex_home))
            self.assertEqual(report["overall"]["status"], "blocked")
            self.assertIn(
                "codex_hook_settings",
                {error.get("component") for error in report["errors"]},
            )
            (hooks_dir / "treewiki-global.json").unlink()
            self._write_hooks(
                codex_home,
                [{"type": "command", "command": "python treewiki_custom_runner.py"}],
            )
            report = diagnose_upgrade(repo, **self._kwargs(skill, codex_home))
            self.assertEqual(report["overall"]["status"], "blocked")

    def test_capture_hook_config_then_hook_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill, repo, codex_home = self._fixture(
                Path(temporary), capture="hook", version=2
            )
            self._write_hooks(
                codex_home, [{"type": "command", "command": "python lmwiki_hook.py"}]
            )
            hook_only = diagnose_upgrade(
                repo, **self._kwargs(skill, codex_home, stages="hook")
            )
            self.assertFalse(any(action["stage"] == "hook" for action in hook_only["actions"]))
            self.assertFalse(hook_only["overall"]["apply_allowed"])
            kwargs = self._kwargs(skill, codex_home, stages="config,hook")
            report = diagnose_upgrade(repo, **kwargs)
            meaningful = [
                action
                for action in report["actions"]
                if action.get("kind") != "safety_prerequisite"
            ]
            self.assertEqual(meaningful[0]["id"], "migrate_repository_config_v3")
            self.assertTrue(all(action["stage"] == "hook" for action in meaningful[1:]))
            apply_upgrade(
                repo,
                plan_id=report["overall"]["plan_id"],
                apply=True,
                principal="user:manager",
                **kwargs,
            )
            current = yaml.safe_load(
                (repo / ".knowledge" / "config.yml").read_text(encoding="utf-8")
            )
            self.assertEqual(current["memory"]["capture"], "explicit")
            payload = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
            values = payload["hooks"]["UserPromptSubmit"][0]["hooks"]
            self.assertEqual(owned_marker(values[0]), "treewiki_hook.py")


class UpgradeSafetyTests(unittest.TestCase):
    def _config_fixture(self, base: Path) -> tuple[Path, Path, dict]:
        skill = make_skill(base / "skill")
        repo = make_repository(base / "repo")
        prepare_backup_ignores(repo)
        kwargs = {
            "skill_root": skill,
            "stages": "config",
            "repository_skill_root": skill,
            "global_skill_root": skill,
            "codex_home": base / "codex",
        }
        return skill, repo, kwargs

    def test_verify_fault_detects_l0_and_docs_mutation(self) -> None:
        for protected_kind in ("l0", "docs"):
            with self.subTest(protected_kind=protected_kind), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                _skill, repo, kwargs = self._config_fixture(base)
                if protected_kind == "l0":
                    protected = repo / ".knowledge" / "private-memory" / "l0" / "note.md"
                else:
                    protected = repo / "docs" / "note.md"
                protected.parent.mkdir(parents=True, exist_ok=True)
                protected.write_text("before\n", encoding="utf-8")
                report = diagnose_upgrade(repo, **kwargs)

                def mutate(phase, action):
                    if phase == "verify" and action["id"] == "migrate_repository_config_v3":
                        protected.write_text("after\n", encoding="utf-8")

                with self.assertRaises(UpgradeException) as caught:
                    apply_upgrade(
                        repo,
                        plan_id=report["overall"]["plan_id"],
                        apply=True,
                        principal="user:manager",
                        fault_injector=mutate,
                        **kwargs,
                    )
                self.assertEqual(caught.exception.code, UpgradeErrorCode.VERIFICATION_FAILED)

    def test_post_apply_verification_failure_is_fsynced_to_journal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            _skill, repo, kwargs = self._config_fixture(base)
            report = diagnose_upgrade(repo, **kwargs)

            def fail_verification(phase, action):
                if phase == "verify" and action["id"] == "migrate_repository_config_v3":
                    raise RuntimeError("verification fault")

            with self.assertRaises(UpgradeException) as caught:
                apply_upgrade(
                    repo,
                    plan_id=report["overall"]["plan_id"],
                    apply=True,
                    principal="user:manager",
                    fault_injector=fail_verification,
                    **kwargs,
                )
            self.assertEqual(caught.exception.code, UpgradeErrorCode.VERIFICATION_FAILED)
            transactions = list((repo / ".knowledge" / "upgrade-backups").iterdir())
            self.assertEqual(len(transactions), 1)
            events = [
                json.loads(line)
                for line in (transactions[0] / "transaction.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            failures = [
                event
                for event in events
                if event.get("phase") == "verify" and event.get("state") == "failed"
            ]
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["action_id"], "migrate_repository_config_v3")
            self.assertEqual(
                failures[0]["error_code"], UpgradeErrorCode.VERIFICATION_FAILED.value
            )
            self.assertEqual(failures[0]["error_type"], "RuntimeError")
            self.assertTrue(failures[0]["recovery"])

    def test_config_apply_runs_real_validator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            _skill, repo, kwargs = self._config_fixture(base)
            invalid = repo / "docs" / "invalid.md"
            invalid.parent.mkdir(parents=True)
            invalid.write_text("no frontmatter\n", encoding="utf-8")
            report = diagnose_upgrade(repo, **kwargs)
            with self.assertRaises(UpgradeException) as caught:
                apply_upgrade(
                    repo,
                    plan_id=report["overall"]["plan_id"],
                    apply=True,
                    principal="user:manager",
                    **kwargs,
                )
            self.assertEqual(caught.exception.code, UpgradeErrorCode.VERIFICATION_FAILED)
            self.assertIn("validation failed", str(caught.exception).lower())

    def test_journal_records_intended_backup_before_replace_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            _skill, repo, kwargs = self._config_fixture(base)
            config_path = repo / ".knowledge" / "config.yml"
            before_hash = sha(config_path.read_bytes())
            report = diagnose_upgrade(repo, **kwargs)

            def fail_before_replace(phase, action):
                if phase == "replace" and action["id"] == "migrate_repository_config_v3":
                    raise RuntimeError("replace fault")

            with self.assertRaises(UpgradeException) as caught:
                apply_upgrade(
                    repo,
                    plan_id=report["overall"]["plan_id"],
                    apply=True,
                    principal="user:manager",
                    fault_injector=fail_before_replace,
                    **kwargs,
                )
            self.assertEqual(caught.exception.code, UpgradeErrorCode.APPLY_FAILED)
            transactions = list((repo / ".knowledge" / "upgrade-backups").iterdir())
            self.assertEqual(len(transactions), 1)
            events = [
                json.loads(line)
                for line in (transactions[0] / "transaction.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            config_events = [
                event
                for event in events
                if event["action_id"] == "migrate_repository_config_v3"
            ]
            self.assertEqual(
                [event["state"] for event in config_events],
                ["planned", "started", "backup_ready", "failed"],
            )
            backup = Path(config_events[0]["backup"])
            self.assertTrue(backup.is_file())
            self.assertEqual(sha(backup.read_bytes()), before_hash)
            self.assertEqual(config_events[0]["before_sha256"], before_hash)

    def test_ignore_prerequisites_precede_sensitive_transaction_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            skill = make_skill(base / "skill")
            repo = make_repository(base / "repo")
            kwargs = {
                "skill_root": skill,
                "stages": "config",
                "repository_skill_root": skill,
                "global_skill_root": skill,
                "codex_home": base / "codex",
            }
            report = diagnose_upgrade(repo, **kwargs)
            self.assertIn(
                "ensure_upgrade_backup_ignore",
                {action["id"] for action in report["actions"]},
            )

            def fail_second_ignore(phase, action):
                if phase == "prerequisite" and action["id"] == "ensure_upgrade_backup_ignore":
                    raise RuntimeError("ignore fault")

            with self.assertRaises(UpgradeException) as caught:
                apply_upgrade(
                    repo,
                    plan_id=report["overall"]["plan_id"],
                    apply=True,
                    principal="user:manager",
                    fault_injector=fail_second_ignore,
                    **kwargs,
                )
            self.assertEqual(caught.exception.code, UpgradeErrorCode.APPLY_FAILED)
            self.assertFalse((repo / ".knowledge" / "upgrade-backups").exists())
            self.assertTrue((repo / ".agents" / "skills" / ".gitignore").is_file())

    def test_memory_target_symlink_or_reparse_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            skill = make_skill(base / "skill")
            repo = make_repository(base / "repo")
            private = repo / ".knowledge" / "private-memory"
            private.mkdir(parents=True)
            docs = repo / "docs"
            docs.mkdir()
            link = docs / "memory"
            try:
                link.symlink_to(private, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            rendered = b"---\nid: MEMORY-LINK\n---\n\nbody\n"
            action = {
                "memory_id": "MEMORY-LINK",
                "target_path": "docs/memory/l1/link.md",
                "level": "l1",
                "body_sha256": sha(b"body\n"),
                "expected_file_sha256": sha(rendered),
                "lineage_digest": lineage_equivalence_digest(
                    "MEMORY-LINK", sha(b"body\n"), "l1", []
                ),
            }

            def planner(root, current_config, approved_ids, *, approvals=None):
                return {
                    "approved_ids": list(approved_ids),
                    "actions": [action],
                    "aggregate_lineage_digest": sha(b"aggregate"),
                }

            report = diagnose_upgrade(
                repo,
                skill_root=skill,
                stages="memory-layout",
                approved_memory_ids=["MEMORY-LINK"],
                memory_layout_planner=planner,
                repository_skill_root=skill,
                global_skill_root=skill,
                codex_home=base / "codex",
            )
            self.assertEqual(report["overall"]["status"], "blocked")
            self.assertIn(
                "symlink",
                " ".join(error["message"] for error in report["errors"]).lower(),
            )


if __name__ == "__main__":
    unittest.main()
