from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills" / "treewiki" / "scripts" / "knowledge_cli.py"


class KnowledgeCliTests(unittest.TestCase):
    def write_config(self, root: Path, *, version: int = 4) -> None:
        (root / ".knowledge").mkdir(parents=True, exist_ok=True)
        vocabulary_dir = root / "docs" / "vocabulary"
        vocabulary_dir.mkdir(parents=True, exist_ok=True)
        (vocabulary_dir / "topics.yml").write_text(
            "test:\n  label: Test\n  aliases: []\n", encoding="utf-8"
        )
        (vocabulary_dir / "glossary.yml").write_text("terms: []\n", encoding="utf-8")
        includes = (
            ["docs/**/*.md", ".knowledge/private-memory/l0/**/*.md"]
            if version >= 3
            else [".knowledge/private-memory/**/*.md"]
        )
        config = {
            "version": version,
            "documents": {"include": includes, "exclude": []},
            "vocabulary_path": "docs/vocabulary/topics.yml",
            "glossary_path": "docs/vocabulary/glossary.yml",
            "memory": {
                "enabled": True,
                "capture": "explicit",
                "private_path": ".knowledge/private-memory",
                "shared_path": "docs/memory",
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
        if version >= 3:
            config["memory"]["layout_version"] = 2 if version >= 4 else 1
        if version >= 4:
            config["memory"]["l3"] = {
                "knowledge_path": "docs/memory/l3/knowledge",
                "persona_path": "docs/memory/l3/persona",
            }
            config["history"] = {"schema": 1, "sidecar": "stable-id"}
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

    def write_shared_memory(
        self,
        root: Path,
        doc_id: str,
        *,
        level: str = "l1",
        subject: str = "user:owner",
        scope: str = "user",
        claim_key: str = "workflow.test",
        claim_value: str = "enabled",
        work: str = "one",
        source: str = "one",
        status: str = "active",
        relations: list[dict[str, str]] | None = None,
        evidence_digest: str | None = None,
    ) -> dict:
        source_ref = f"local-memory:install-{source}:work-{work}"
        source_hash = "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()
        sharing = {
            "authored_by": "agent:treewiki",
            "shared_by": ["user:owner"],
            "shared_at": "2026-08-08T00:00:00Z",
            "approved_by": [] if level == "l3" and status == "proposed" else ["user:owner"],
            "approved_at": None if level == "l3" and status == "proposed" else "2026-08-08T00:00:00Z",
            "evidence_digest": evidence_digest
            or "sha256:" + hashlib.sha256(doc_id.encode("utf-8")).hexdigest(),
            "source_ref": source_ref,
            "source_hash": source_hash,
            "source_machine": "install:test",
            "work_unit_id": f"work:{work}",
        }
        metadata = {
            "id": doc_id,
            "title": "test",
            "type": "persona" if level == "l3" else "memory",
            "status": status,
            "authority": "informative",
            "topics": ["test"],
            "summary": "test",
            "relations": relations or [],
            "reviewed": "2026-08-08",
            "memory": {
                "level": level,
                "subject": subject,
                "kind": "preference",
                "scope": scope,
                "claim_key": claim_key,
                "claim_value": claim_value,
                "confirmed_by": "user:owner",
                "confidence": 1.0,
            },
            "sharing": sharing,
            "access": {
                "visibility": "team",
                "owner": "user:owner",
                "team": "team:repo",
                "grants": [],
            },
        }
        if level == "l3":
            metadata["category"] = "persona"
        target = root / "docs" / "memory" / level / f"{doc_id.casefold()}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "---\n"
            + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
            + "---\n\n# test\n",
            encoding="utf-8",
        )
        return metadata

    def write_legacy_memory(self, root: Path, doc_id: str) -> Path:
        metadata = {
            "id": doc_id,
            "title": "legacy private memory",
            "type": "memory",
            "status": "active",
            "authority": "informative",
            "topics": ["test"],
            "summary": "legacy",
            "relations": [],
            "reviewed": "2026-08-08",
            "memory": {"level": "l1", "subject": "legacy-slug", "confidence": 1.0},
            "access": {
                "visibility": "private",
                "owner": "user:owner",
                "team": "team:repo",
                "grants": [],
            },
        }
        target = root / ".knowledge" / "private-memory" / "l1" / "legacy.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
            + "---\n\n    preserved legacy body\n",
            encoding="utf-8",
        )
        return target

    def write_memory_approval(self, path: Path, doc_id: str, claim_value: str) -> None:
        approval = {
            "approvals": {
                doc_id: {
                    "level": "l1",
                    "subject": "user:owner",
                    "scope": "user",
                    "kind": "preference",
                    "claim_key": "workflow.legacy",
                    "claim_value": claim_value,
                    "access": {
                        "owner": "user:owner",
                        "team": "team:repo",
                        "grants": [],
                    },
                    "sharing": {
                        "authored_by": "agent:treewiki",
                        "shared_by": ["user:owner"],
                        "shared_at": "2026-08-08T00:00:00Z",
                        "approved_by": ["user:owner"],
                        "approved_at": "2026-08-08T00:00:00Z",
                        "evidence_digest": "sha256:" + "1" * 64,
                        "source_ref": "local-memory:legacy",
                        "source_hash": "sha256:" + "2" * 64,
                        "source_machine": "install:test",
                        "work_unit_id": "work:legacy",
                    },
                    "sensitivity_review": {
                        "decision": "share",
                        "reviewed_by": "user:owner",
                        "reviewed_at": "2026-08-08T00:00:00Z",
                        "checks": [
                            "secrets", "third_party_pii", "local_paths", "device_names"
                        ],
                    },
                }
            }
        }
        path.write_text(
            yaml.safe_dump(approval, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    def evidence_digest(self, records: list[dict]) -> str:
        evidence = [
            {
                "id": record["id"],
                "source_ref": record["sharing"]["source_ref"],
                "source_hash": record["sharing"]["source_hash"],
                "work_unit_id": record["sharing"]["work_unit_id"],
            }
            for record in sorted(records, key=lambda item: item["id"])
        ]
        payload = json.dumps(
            evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(payload).hexdigest()

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
            self.write_shared_memory(root, "MEMORY-L1-TEST-003", work="work-1", source="one")
            self.write_shared_memory(root, "MEMORY-L1-TEST-004", work="work-2", source="two")

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
            self.assertEqual(json.loads(allowed.stdout)["schema"], "treewiki.l3-candidates/v2")
            self.assertIn('"subject":"user:owner"', allowed.stdout)
            self.assertIn('"scope":"user"', allowed.stdout)
            self.assertIn('"claim_key":"workflow.test"', allowed.stdout)
            self.assertIn('"claim_value":"enabled"', allowed.stdout)
            self.assertIn('"status":"eligible"', allowed.stdout)
            self.assertIn('"proposal_status":"proposed"', allowed.stdout)
            self.assertIn('"MEMORY-L1-TEST-003"', allowed.stdout)
            self.assertIn('"MEMORY-L1-TEST-004"', allowed.stdout)
            self.assertIn('"local-memory:install-one:work-work-1', allowed.stdout)

            denied = self.run_cli(
                "query",
                "l3-candidates",
                str(root),
                "--principal",
                "user:other",
                "--team",
                "team:other",
            )
            self.assertEqual(denied.returncode, 0, denied.stdout + denied.stderr)
            self.assertEqual(denied.stdout.strip(), "NO L3 CLAIM GROUPS")

    def test_l3_candidates_do_not_count_l1_and_derived_l2_twice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root)
            self.write_shared_memory(
                root, "MEMORY-L1-TEST-002", work="one-work", source="raw-one"
            )
            self.write_shared_memory(
                root,
                "MEMORY-L2-TEST-003",
                level="l2",
                work="one-work",
                source="derived",
                relations=[
                    {"type": "distilled_from", "target": "MEMORY-L1-TEST-002"}
                ],
            )
            result = self.run_cli(
                "query", "l3-candidates", str(root),
                "--principal", "user:owner", "--team", "team:repo",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("status=insufficient_evidence", result.stdout)
            self.assertIn("evidence=1/2", result.stdout)

    def test_preferences_are_returned_without_task_search_terms(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root)
            self.write_shared_memory(root, "MEMORY-L1-TEST-002")
            result = self.run_cli(
                "query", "preferences", str(root),
                "--principal", "user:owner", "--team", "team:repo", "--json",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('"id":"MEMORY-L1-TEST-002"', result.stdout)

    def test_upgrade_status_validates_identity_without_requiring_manager(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root)
            result = self.run_cli(
                "manage", "upgrade-status", str(root), "--offline", "--json",
                "--principal", "user:reader", "--team", "team:other",
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema"], "treewiki.upgrade-status/v1")
            self.assertTrue(payload["overall"]["plan_id"].startswith("sha256:"))

            invalid = self.run_cli(
                "manage", "upgrade-status", str(root), "--offline", "--json",
                "--principal", "reader", "--team", "team:other",
            )
            self.assertEqual(invalid.returncode, 4, invalid.stdout + invalid.stderr)
            self.assertEqual(json.loads(invalid.stdout)["error"]["code"], "INVALID_INPUT")

    def test_upgrade_dry_run_requires_manager_and_exact_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root)
            status = self.run_cli(
                "manage", "upgrade-status", str(root), "--offline", "--json",
                "--principal", "user:owner", "--team", "team:repo",
            )
            plan_id = json.loads(status.stdout)["overall"]["plan_id"]
            denied = self.run_cli(
                "manage", "upgrade", str(root), "--plan-id", plan_id, "--offline", "--json",
                "--principal", "user:reader", "--team", "team:repo",
            )
            self.assertEqual(denied.returncode, 4, denied.stdout + denied.stderr)
            self.assertEqual(json.loads(denied.stdout)["error"]["code"], "MANAGEMENT_DENIED")

            allowed = self.run_cli(
                "manage", "upgrade", str(root), "--plan-id", plan_id, "--offline", "--json",
                "--principal", "user:owner", "--team", "team:repo",
            )
            self.assertEqual(allowed.returncode, 2, allowed.stdout + allowed.stderr)
            self.assertEqual(json.loads(allowed.stdout)["overall"]["plan_id"], plan_id)

    def test_upgrade_status_and_upgrade_share_exact_stage_and_global_approval_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root)
            identity = ("--principal", "user:owner", "--team", "team:repo")
            status = self.run_cli(
                "manage", "upgrade-status", str(root), "--offline", "--json",
                "--stage", "skill", "--approve-global-skill", *identity,
            )
            self.assertIn(status.returncode, {0, 2}, status.stdout + status.stderr)
            payload = json.loads(status.stdout)
            self.assertTrue(
                any(action["id"] == "copy_global_treewiki_skill" for action in payload["actions"])
            )
            dry_run = self.run_cli(
                "manage", "upgrade", str(root), "--plan-id", payload["overall"]["plan_id"],
                "--offline", "--json", "--stage", "skill", "--approve-global-skill", *identity,
            )
            self.assertNotEqual(dry_run.returncode, 6, dry_run.stdout + dry_run.stderr)
            self.assertEqual(
                json.loads(dry_run.stdout)["overall"]["plan_id"], payload["overall"]["plan_id"]
            )

    def test_memory_approval_file_is_bound_to_plan_without_value_or_path_disclosure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root, version=2)
            doc_id = "MEMORY-L1-PRIVATE-001"
            self.write_legacy_memory(root, doc_id)
            approval_path = root / "TOP-SECRET-approval.yml"
            self.write_memory_approval(approval_path, doc_id, "SECRET-VALUE-ONE")
            identity = ("--principal", "user:owner", "--team", "team:repo")
            shared = (
                "--stage", "memory-layout", "--approve-memory-id", doc_id,
                "--memory-approval-file", str(approval_path),
            )
            status = self.run_cli(
                "manage", "upgrade-status", str(root), "--offline", "--json", *shared, *identity,
            )
            self.assertIn(status.returncode, {0, 2}, status.stdout + status.stderr)
            self.assertNotIn("TOP-SECRET", status.stdout)
            self.assertNotIn("SECRET-VALUE-ONE", status.stdout)
            first_plan = json.loads(status.stdout)["overall"]["plan_id"]

            exact = self.run_cli(
                "manage", "upgrade", str(root), "--plan-id", first_plan, "--offline", "--json",
                *shared, *identity,
            )
            self.assertNotEqual(exact.returncode, 6, exact.stdout + exact.stderr)

            self.write_memory_approval(approval_path, doc_id, "SECRET-VALUE-TWO")
            changed = self.run_cli(
                "manage", "upgrade-status", str(root), "--offline", "--json", *shared, *identity,
            )
            self.assertNotIn("SECRET-VALUE-TWO", changed.stdout)
            self.assertNotEqual(json.loads(changed.stdout)["overall"]["plan_id"], first_plan)
            stale = self.run_cli(
                "manage", "upgrade", str(root), "--plan-id", first_plan, "--offline", "--json",
                *shared, *identity,
            )
            self.assertEqual(stale.returncode, 6, stale.stdout + stale.stderr)

            mismatch = self.run_cli(
                "manage", "upgrade-status", str(root), "--offline", "--json",
                "--stage", "memory-layout", "--memory-approval-file", str(approval_path), *identity,
            )
            self.assertEqual(mismatch.returncode, 4, mismatch.stdout + mismatch.stderr)
            self.assertNotIn(str(approval_path), mismatch.stdout)

    def test_l3_review_is_dry_run_then_owner_approved_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root)
            first = self.write_shared_memory(
                root, "MEMORY-L1-A", work="one", source="one"
            )
            second = self.write_shared_memory(
                root, "MEMORY-L1-B", work="two", source="two"
            )
            digest = self.evidence_digest([first, second])
            proposal = self.write_shared_memory(
                root,
                "PERSONA-TEST-001",
                level="l3",
                work="persona",
                source="persona",
                status="proposed",
                relations=[
                    {"type": "distilled_from", "target": "MEMORY-L1-A"},
                    {"type": "distilled_from", "target": "MEMORY-L1-B"},
                ],
                evidence_digest=digest,
            )
            identity = ("--principal", "user:owner", "--team", "team:repo")
            dry_run = self.run_cli(
                "manage", "l3-review", str(root), proposal["id"],
                "--candidate-digest", digest, "--decision", "approve", "--json",
                *identity,
            )
            self.assertEqual(dry_run.returncode, 0, dry_run.stdout + dry_run.stderr)
            review_plan = json.loads(dry_run.stdout)
            self.assertEqual(review_plan["status"], "planned")
            target = root / "docs" / "memory" / "l3" / "persona-test-001.md"
            self.assertEqual(yaml.safe_load(target.read_text(encoding="utf-8").split("---")[1])["status"], "proposed")

            applied = self.run_cli(
                "manage", "l3-review", str(root), proposal["id"],
                "--candidate-digest", digest, "--decision", "approve",
                "--plan-id", review_plan["plan_id"], "--apply", "--json",
                *identity,
            )
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            payload = json.loads(applied.stdout)
            self.assertEqual(payload["status"], "APPLIED")
            metadata = yaml.safe_load(target.read_text(encoding="utf-8").split("---")[1])
            self.assertEqual(metadata["status"], "active")
            self.assertEqual(metadata["sharing"]["approved_by"], ["user:owner"])
            self.assertTrue(Path(payload["backup_path"]).joinpath("transaction.jsonl").is_file())

    def test_l3_review_rejects_stale_digest_with_exit_6(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root)
            proposal = self.write_shared_memory(
                root, "PERSONA-TEST-STALE", level="l3", status="proposed"
            )
            stale = "sha256:" + "0" * 64
            result = self.run_cli(
                "manage", "l3-review", str(root), proposal["id"],
                "--candidate-digest", stale, "--decision", "reject", "--apply", "--json",
                "--principal", "user:owner", "--team", "team:repo",
            )
            self.assertEqual(result.returncode, 6, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["error"]["code"], "STALE_PLAN")

    def test_l3_review_blocks_one_evidence_but_reject_records_nonapproval_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root)
            first = self.write_shared_memory(root, "MEMORY-L1-ONLY", work="one", source="one")
            digest = self.evidence_digest([first])
            proposal = self.write_shared_memory(
                root, "PERSONA-TEST-ONE", level="l3", status="proposed",
                relations=[{"type": "distilled_from", "target": first["id"]}],
                evidence_digest=digest,
            )
            identity = ("--principal", "user:owner", "--team", "team:repo")
            blocked = self.run_cli(
                "manage", "l3-review", str(root), proposal["id"],
                "--candidate-digest", digest, "--decision", "approve", "--json", *identity,
            )
            self.assertEqual(blocked.returncode, 3, blocked.stdout + blocked.stderr)
            self.assertEqual(json.loads(blocked.stdout)["error"]["code"], "BLOCKED")

            reject_plan = self.run_cli(
                "manage", "l3-review", str(root), proposal["id"],
                "--candidate-digest", digest, "--decision", "reject", "--json", *identity,
            )
            self.assertEqual(reject_plan.returncode, 0, reject_plan.stdout + reject_plan.stderr)
            rejected = self.run_cli(
                "manage", "l3-review", str(root), proposal["id"],
                "--candidate-digest", digest, "--decision", "reject", "--plan-id",
                json.loads(reject_plan.stdout)["plan_id"], "--apply", "--json", *identity,
            )
            self.assertEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)
            target = root / "docs" / "memory" / "l3" / "persona-test-one.md"
            metadata = yaml.safe_load(target.read_text(encoding="utf-8").split("---")[1])
            self.assertEqual(metadata["status"], "rejected")
            self.assertEqual(metadata["sharing"]["approved_by"], [])
            self.assertEqual(metadata["sharing"]["reviewed_by"], "user:owner")
            self.assertEqual(metadata["sharing"]["review_decision"], "reject")

    def test_migrate_is_read_only_upgrade_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root, version=1)
            identity = ("--principal", "user:owner", "--team", "team:repo")

            plan = self.run_cli("manage", "migrate", str(root), *identity)
            self.assertEqual(plan.returncode, 2, plan.stdout + plan.stderr)
            self.assertIn("DEPRECATED", plan.stdout)
            self.assertIn("manage upgrade-status", plan.stdout)
            self.assertEqual(
                yaml.safe_load((root / ".knowledge" / "config.yml").read_text(encoding="utf-8"))[
                    "version"
                ],
                1,
            )

            applied = self.run_cli("manage", "migrate", str(root), "--apply", *identity)
            self.assertEqual(applied.returncode, 2, applied.stdout + applied.stderr)
            self.assertIn("NO CHANGES APPLIED", applied.stdout)
            config = yaml.safe_load(
                (root / ".knowledge" / "config.yml").read_text(encoding="utf-8")
            )
            self.assertEqual(config["version"], 1)

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
            self.assertEqual(plan.returncode, 2, plan.stdout + plan.stderr)
            self.assertIn("NO CHANGES APPLIED", plan.stdout)
            self.assertEqual(stale.read_text(encoding="utf-8"), "stale\n")

            applied = self.run_cli(
                "manage",
                "migrate",
                str(root),
                "--sync-skill-copy",
                "--apply",
                *identity,
            )
            self.assertEqual(applied.returncode, 2, applied.stdout + applied.stderr)
            self.assertEqual(stale.read_text(encoding="utf-8"), "stale\n")

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
            self.assertEqual(plan.returncode, 2, plan.stdout + plan.stderr)
            self.assertIn("NO CHANGES APPLIED", plan.stdout)
            self.assertEqual(stale.read_text(encoding="utf-8"), "stale\n")

            applied = self.run_cli(
                "manage", "migrate", str(root), "--apply", *options, *identity
            )
            self.assertEqual(applied.returncode, 2, applied.stdout + applied.stderr)
            self.assertEqual(stale.read_text(encoding="utf-8"), "stale\n")

    def test_memory_finalize_is_dry_run_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root)
            result = self.run_cli(
                "manage", "memory-finalize", str(root),
                "--principal", "user:owner", "--team", "team:repo",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("MEMORY FINALIZE lifecycle -> validate -> rebuild derived indexes", result.stdout)
            self.assertIn("DRY-RUN", result.stdout)

    def test_memory_finalize_apply_validates_and_rebuilds_bm25(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root)
            self.write_memory(
                root, 1, level="l0", subject="user:owner", provenance="conversation:saved"
            )
            dry_run = self.run_cli(
                "manage", "memory-finalize", str(root),
                "--principal", "user:owner", "--team", "team:repo",
            )
            self.assertEqual(dry_run.returncode, 0, dry_run.stdout + dry_run.stderr)
            plan_id = next(
                line.removeprefix("PLAN ID ")
                for line in dry_run.stdout.splitlines()
                if line.startswith("PLAN ID ")
            )
            result = self.run_cli(
                "manage", "memory-finalize", str(root), "--plan-id", plan_id, "--apply",
                "--principal", "user:owner", "--team", "team:repo",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Validated 1 documents: 0 errors", result.stdout)
            self.assertTrue((root / ".knowledge" / "index" / "search.db").is_file())

    def test_memory_finalize_blocks_config_v2(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_config(root, version=2)
            result = self.run_cli(
                "manage", "memory-finalize", str(root), "--apply",
                "--principal", "user:owner", "--team", "team:repo",
            )
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn("requires config v4/layout 2", result.stderr)


if __name__ == "__main__":
    unittest.main()
