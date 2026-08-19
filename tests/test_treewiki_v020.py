from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "treewiki" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_adapter_bundles  # noqa: E402
import document_history  # noqa: E402
import memory_policy  # noqa: E402
from claude_alias import ClaudeAliasError, apply_alias, plan_alias  # noqa: E402
from okf_v02 import export_concept  # noqa: E402


ZERO_HASH = "sha256:" + "0" * 64


def write_document(path: Path, metadata: dict, body: str = "# Body\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
        + "---\n\n"
        + body,
        encoding="utf-8",
        newline="\n",
    )


def candidate_metadata(doc_id: str = "MEMORY-L3-RULE-004") -> dict:
    return {
        "id": doc_id,
        "title": "Candidate",
        "type": "memory",
        "status": "proposed",
        "authority": "informative",
        "topics": ["test"],
        "summary": "candidate",
        "relations": [],
        "reviewed": None,
        "category": "knowledge",
        "memory": {
            "level": "l3",
            "subject": "team:repo",
            "scope": "repo",
            "kind": "rule",
            "claim_key": "workflow.review",
            "claim_value": "required",
        },
        "access": {
            "visibility": "team",
            "owner": "user:owner",
            "team": "team:repo",
            "grants": [],
        },
    }


class DocumentHistoryTests(unittest.TestCase):
    def test_candidate_notice_once_and_verification_does_not_increment_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = root / "docs" / "memory" / "l3" / "knowledge" / "candidate.md"
            metadata = candidate_metadata()
            write_document(document, metadata)

            plan = document_history.plan_documents(
                root,
                [document],
                actor="user:owner",
                created_ids=[metadata["id"]],
                at="2026-08-19T00:00:00Z",
            )
            result = document_history.apply_document_plan(
                root, plan, plan_id=plan["plan_id"]
            )
            self.assertEqual([event["type"] for event in result["events"]], ["L3_CANDIDATE_CREATED"])
            finalized, _, _ = document_history.parse_document(document)
            self.assertEqual(finalized["revision"], 1)
            self.assertEqual(finalized["created_at"], "2026-08-19T00:00:00Z")

            no_op = document_history.plan_documents(
                root, [document], actor="user:owner", created_ids=[metadata["id"]]
            )
            self.assertEqual(no_op["status"], "current")
            self.assertEqual(no_op["actions"], [])

            verify = document_history.plan_verification(
                root,
                document,
                actor="user:owner",
                source_digest=ZERO_HASH,
                reason="source rechecked",
                at="2026-08-20T00:00:00Z",
            )
            document_history.apply_verification(root, verify, plan_id=verify["plan_id"])
            verified, _, _ = document_history.parse_document(document)
            self.assertEqual(verified["revision"], 1)
            self.assertEqual(verified["modified_at"], "2026-08-19T00:00:00Z")
            self.assertEqual(verified["verified_at"], "2026-08-20T00:00:00Z")
            events = document_history.read_history(
                document_history.history_path_for(document, metadata["id"])
            )
            self.assertEqual([event["event"] for event in events], ["created", "verified"])

    def test_no_git_history_keeps_created_and_modified_dates_null(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = root / "docs" / "reference.md"
            metadata = candidate_metadata("REFERENCE-001")
            metadata.update({"type": "reference", "status": "active"})
            metadata.pop("memory")
            metadata.pop("category")
            write_document(document, metadata)
            plan = document_history.plan_documents(
                root, [document], actor="user:owner", at="2026-08-19T00:00:00Z"
            )
            document_history.apply_document_plan(root, plan, plan_id=plan["plan_id"])
            finalized, _, _ = document_history.parse_document(document)
            self.assertIsNone(finalized["created_at"])
            self.assertIsNone(finalized["modified_at"])
            events = document_history.read_history(
                document_history.history_path_for(document, "REFERENCE-001")
            )
            self.assertEqual(events[0]["event"], "migrated")

    def test_partial_replace_failure_restores_document_and_removes_new_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = root / "docs" / "reference.md"
            metadata = candidate_metadata("REFERENCE-ROLLBACK")
            metadata.update({"type": "reference", "status": "active"})
            metadata.pop("memory")
            metadata.pop("category")
            write_document(document, metadata)
            before = document.read_bytes()
            plan = document_history.plan_documents(
                root,
                [document],
                actor="user:owner",
                created_ids=["REFERENCE-ROLLBACK"],
                at="2026-08-19T00:00:00Z",
            )
            real_replace = os.replace
            calls = 0

            def fail_second(source: str | Path, target: str | Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("sidecar replace fault")
                real_replace(source, target)

            with mock.patch.object(document_history.os, "replace", side_effect=fail_second):
                with self.assertRaises(OSError):
                    document_history.apply_document_plan(root, plan, plan_id=plan["plan_id"])
            self.assertEqual(document.read_bytes(), before)
            self.assertFalse(
                document_history.history_path_for(document, "REFERENCE-ROLLBACK").exists()
            )

    def test_document_and_stable_id_sidecar_move_together(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "docs" / "old" / "reference.md"
            metadata = candidate_metadata("REFERENCE-MOVE")
            metadata.update({"type": "reference", "status": "active"})
            metadata.pop("memory")
            metadata.pop("category")
            write_document(source, metadata)
            finalize = document_history.plan_documents(
                root,
                [source],
                actor="user:owner",
                created_ids=["REFERENCE-MOVE"],
                at="2026-08-19T00:00:00Z",
            )
            document_history.apply_document_plan(root, finalize, plan_id=finalize["plan_id"])
            destination = root / "docs" / "new" / "reference.md"
            move = document_history.plan_document_move(root, source, destination)
            result = document_history.apply_document_move(root, move, plan_id=move["plan_id"])
            self.assertEqual(result["status"], "APPLIED")
            self.assertFalse(source.exists())
            self.assertTrue(destination.is_file())
            self.assertTrue(
                document_history.history_path_for(destination, "REFERENCE-MOVE").is_file()
            )


class L3ThresholdTests(unittest.TestCase):
    @staticmethod
    def record(
        doc_id: str,
        *,
        kind: str,
        work: str,
        source: str,
        evidence_mode: str | None = None,
        authored_by: str = "agent:treewiki",
        supports_claim: dict | None = None,
    ) -> dict:
        memory = {
            "level": "l1",
            "subject": "user:owner",
            "scope": "user",
            "kind": kind,
            "claim_key": f"source.{doc_id}",
            "claim_value": doc_id,
        }
        if evidence_mode:
            memory["evidence_mode"] = evidence_mode
        if supports_claim:
            memory["supports_claim"] = supports_claim
        return {
            "metadata": {
                "id": doc_id,
                "status": "active",
                "authority": "informative",
                "relations": [],
                "memory": memory,
                "sharing": {
                    "authored_by": authored_by,
                    "work_unit_id": f"work:{work}",
                    "source_ref": f"local-memory:{source}",
                    "source_hash": ZERO_HASH,
                },
            }
        }

    def test_single_authoritative_fact_and_explicit_preference_are_eligible(self) -> None:
        fact = self.record(
            "FACT-1",
            kind="fact",
            work="fact",
            source="official",
            evidence_mode="authoritative",
            supports_claim={
                "kind": "fact",
                "claim_key": "runtime.version",
                "claim_value": "0.2.0",
            },
        )
        preference = self.record(
            "PREF-1",
            kind="preference",
            work="preference",
            source="declaration",
            evidence_mode="explicit",
            authored_by="user:owner",
            supports_claim={
                "kind": "preference",
                "claim_key": "workflow.notice",
                "claim_value": "terminal",
            },
        )
        groups = memory_policy.l3_candidate_groups([fact, preference])
        self.assertEqual({item["kind"]: item["status"] for item in groups}, {"fact": "eligible", "preference": "eligible"})
        self.assertTrue(all(item["minimum_sources"] == 1 for item in groups))

    def test_convergent_information_uses_two_independent_observations(self) -> None:
        projection = {
            "kind": "information",
            "claim_key": "build.reliability",
            "claim_value": "staging-required",
        }
        records = [
            self.record("OBS-1", kind="fact", work="one", source="one", supports_claim=projection),
            self.record("OBS-2", kind="fact", work="two", source="two", supports_claim=projection),
        ]
        group = memory_policy.l3_candidate_groups(records)[0]
        self.assertEqual(group["kind"], "information")
        self.assertEqual(group["status"], "eligible")
        self.assertEqual(group["evidence_count"], 2)

    def test_repeated_preference_waits_for_user_confirmation(self) -> None:
        projection = {
            "kind": "preference",
            "claim_key": "workflow.output",
            "claim_value": "terminal-notice",
        }
        records = [
            self.record("PREF-A", kind="preference", work="one", source="one", supports_claim=projection),
            self.record("PREF-B", kind="preference", work="two", source="two", supports_claim=projection),
        ]
        group = memory_policy.l3_candidate_groups(records)[0]
        self.assertEqual(group["status"], "confirmation_required")
        records[0]["metadata"]["memory"]["confirmed_by"] = "user:owner"
        self.assertEqual(memory_policy.l3_candidate_groups(records)[0]["status"], "eligible")


class AdapterAndCompatibilityTests(unittest.TestCase):
    def test_readmes_document_installable_claude_and_agent_plugins(self) -> None:
        marketplace = json.loads(
            (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        )
        self.assertEqual(marketplace["name"], "treewiki-marketplace")
        self.assertEqual(len(marketplace["plugins"]), 1)
        plugin = marketplace["plugins"][0]
        self.assertEqual(plugin["name"], "treewiki")
        self.assertEqual(plugin["source"], "./plugins/treewiki-claude")
        self.assertEqual(plugin["version"], "0.2.0")

        for readme_name in ("README.md", "README.ko.md"):
            readme = (ROOT / readme_name).read_text(encoding="utf-8")
            self.assertIn("/plugin marketplace add j-token/treewiki", readme)
            self.assertIn("/plugin install treewiki@treewiki-marketplace", readme)
            self.assertIn("manage setup-claude-alias", readme)
            self.assertIn("codex plugin marketplace add j-token/treewiki --ref v0.2.0", readme)
            self.assertIn("codex plugin add treewiki@treewiki-marketplace", readme)
            self.assertIn("TreeWiki Workbench", readme)

    def test_claude_alias_scope_shadow_and_plugin_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            repository.mkdir()
            plugin = base / "plugin"
            manifest = plugin / ".claude-plugin" / "plugin.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text('{"name":"treewiki","version":"0.2.0"}\n', encoding="utf-8")
            source = ROOT / "skills" / "treewiki" / "assets" / "claude-alias" / "SKILL.md"
            with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(base / "claude")}, clear=False):
                user = plan_alias(repository, scope="user", plugin_root=plugin, alias_source=source)
                apply_alias(user, plan_id=user["plan_id"])
                project = plan_alias(repository, scope="project", plugin_root=plugin, alias_source=source)
                apply_alias(project, plan_id=project["plan_id"])
                shadowed = plan_alias(repository, scope="project", plugin_root=plugin, alias_source=source)
                self.assertEqual(shadowed["shadow"]["warning"], "ALIAS_SHADOWED")
                self.assertIn("0.2.0", Path(user["target"]).read_text(encoding="utf-8"))
            with self.assertRaises(ClaudeAliasError):
                plan_alias(repository, scope="", plugin_root=plugin, alias_source=source)
            manifest.write_text('{"name":"treewiki","version":"0.1.0"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ClaudeAliasError, "upgrade.*0.2.0"):
                plan_alias(repository, scope="project", plugin_root=plugin, alias_source=source)

    def test_codex_claude_and_agent_plugin_runtime_hashes_are_identical(self) -> None:
        result = build_adapter_bundles.build(ROOT, check=True)
        self.assertEqual(result["mismatches"], [])
        claude_runtime = json.loads(
            (ROOT / "plugins" / "treewiki-claude" / "runtime" / "runtime-manifest.json").read_text(encoding="utf-8")
        )
        agent_runtime = json.loads(
            (ROOT / "plugins" / "treewiki" / "runtime-manifest.json").read_text(encoding="utf-8")
        )
        release = yaml.safe_load(
            (ROOT / "skills" / "treewiki" / "treewiki-release.yml").read_text(encoding="utf-8")
        )
        self.assertEqual(claude_runtime, agent_runtime)
        self.assertEqual(claude_runtime["release_version"], release["release"])
        self.assertEqual(claude_runtime["core_hash"], release["runtime"]["core_hash"])
        self.assertEqual(release["adapters"]["codex"]["kind"], "agent-plugin")
        self.assertEqual(release["adapters"]["codex"]["specification"], "agent-plugins/1.0.0-working-draft")
        self.assertEqual(release["adapters"]["codex"]["ui_resource"], "ui://treewiki/workbench-v1.html")

    def test_agent_plugin_uses_workbench_and_exact_plan_apply(self) -> None:
        plugin = ROOT / "plugins" / "treewiki"
        server = (plugin / "src" / "server.ts").read_text(encoding="utf-8")
        widget = (plugin / "web" / "src" / "workbench.html").read_text(encoding="utf-8")
        package = json.loads((plugin / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["version"], "0.2.0")
        self.assertIn('"search"', server)
        self.assertIn('"fetch"', server)
        self.assertIn("RESOURCE_MIME_TYPE", server)
        self.assertIn("ui: { resourceUri: WORKBENCH_URI", server)
        self.assertIn('"apply_l3_review"', server)
        self.assertIn('"apply_upgrade_stage"', server)
        self.assertIn('"apply_binding_change"', server)
        self.assertIn("candidateDigest", server)
        self.assertIn("planId", server)
        self.assertIn('rpc("ui/initialize"', widget)
        self.assertIn('rpc("tools/call"', widget)
        self.assertIn('rpc("ui/message"', widget)
        self.assertIn('rpc("ui/update-model-context"', widget)
        self.assertIn("window.openai?.requestDisplayMode", widget)
        for screen in ("setup", "overview", "search", "history", "l3", "upgrade"):
            self.assertIn(f'id="{screen}"', widget)

    def test_router_fixtures_cover_six_modes_and_progressive_references(self) -> None:
        plugin = ROOT / "plugins" / "treewiki-claude"
        fixtures = yaml.safe_load((plugin / "tests" / "routing-fixtures.yml").read_text(encoding="utf-8"))
        modes = {item["expected_mode"] for item in fixtures["fixtures"]}
        self.assertEqual(modes, {"adopt", "query", "update", "remember", "review", "upgrade"})
        router = (plugin / "skills" / "route" / "SKILL.md").read_text(encoding="utf-8")
        for mode in modes:
            self.assertIn(f"references/{mode}.md", router)
            self.assertTrue((plugin / "skills" / "route" / "references" / f"{mode}.md").is_file())
        self.assertIn("$ARGUMENTS", router)
        self.assertNotIn("L3_CANDIDATE_CREATED", (ROOT / "skills" / "treewiki" / "scripts" / "treewiki_hook.py").read_text(encoding="utf-8"))

    def test_okf_export_maps_lifecycle_status_sources_and_verification(self) -> None:
        metadata = candidate_metadata("KNOWLEDGE-OKF-001")
        metadata.update(
            {
                "modified_at": "2026-08-19T00:00:00Z",
                "revision": 2,
                "provenance": [{"source": "docs/source.md"}],
            }
        )
        concept = export_concept(
            metadata,
            "# Knowledge\n",
            [
                {
                    "event": "verified",
                    "at": "2026-08-20T00:00:00Z",
                    "actor": "user:owner",
                    "source": ZERO_HASH,
                }
            ],
        )
        frontmatter = concept["frontmatter"]
        self.assertEqual(frontmatter["generated"]["at"], "2026-08-19T00:00:00Z")
        self.assertEqual(frontmatter["status"], "draft")
        self.assertEqual(frontmatter["sources"][0]["resource"], "docs/source.md")
        self.assertEqual(frontmatter["verified"][0]["at"], "2026-08-20T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
