from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "treewiki" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import memory_policy  # noqa: E402


ZERO_HASH = "sha256:" + "0" * 64


def config_v3() -> dict:
    """Current v5 fixture; legacy function name keeps older test call sites compact."""
    return {
        "version": 5,
        "documents": {
            "include": [
                "AGENTS.md",
                "docs/**/*.md",
                ".knowledge/private-memory/l0/**/*.md",
            ],
            "exclude": [],
        },
        "memory": {
            "layout_version": 2,
            "private_path": ".knowledge/private-memory",
            "shared_path": "docs/memory",
            "l3": {
                "knowledge_path": "docs/memory/l3/knowledge",
                "persona_path": "docs/memory/l3/persona",
            },
        },
        "history": {
            "schema": 1,
            "storage": "local",
            "path": ".knowledge/document-history",
            "enforce": True,
        },
    }


def sharing(work: str, source: str, *, approved: bool = True) -> dict:
    return {
        "authored_by": "agent:treewiki",
        "shared_by": ["user:owner"],
        "shared_at": "2026-08-08T00:00:00Z",
        "approved_by": ["user:owner"] if approved else [],
        "approved_at": "2026-08-08T00:00:00Z" if approved else None,
        "evidence_digest": ZERO_HASH,
        "source_ref": f"local-memory:{source}",
        "source_hash": ZERO_HASH,
        "source_machine": "install:opaque",
        "work_unit_id": f"work:{work}",
    }


def record(
    doc_id: str,
    *,
    level: str = "l1",
    work: str,
    source: str,
    value: str = "skill-over-hook",
    parent: str | None = None,
    status: str = "active",
) -> dict:
    relations = [{"type": "distilled_from", "target": parent}] if parent else []
    return {
        "path": f"docs/memory/{level}/{doc_id.lower()}.md",
        "metadata": {
            "id": doc_id,
            "type": "persona" if level == "l3" else "memory",
            "status": status,
            "relations": relations,
            "memory": {
                "level": level,
                "subject": "user:owner",
                "kind": "preference",
                "scope": "user",
                "claim_key": "workflow.context-aware-automation",
                "claim_value": value,
                "confirmed_by": "user:owner",
                "confidence": 1.0,
            },
            "sharing": sharing(work, source),
            "access": {
                "visibility": "team",
                "owner": "user:owner",
                "team": "team:repository",
                "grants": [],
            },
        },
    }


class ConfigAndMutationTests(unittest.TestCase):
    def test_config_v5_is_required_for_writes(self) -> None:
        memory_policy.require_config_v3(config_v3())
        old = config_v3()
        old["version"] = 3
        with self.assertRaisesRegex(memory_policy.MemoryPolicyError, "version must be 5") as caught:
            memory_policy.require_config_v3(old)
        self.assertEqual(caught.exception.code, "CONFIG_UPGRADE_REQUIRED")
        newer = config_v3()
        newer["version"] = 6
        with self.assertRaises(memory_policy.MemoryPolicyError) as caught:
            memory_policy.require_config_v3(newer)
        self.assertEqual(caught.exception.code, "INCOMPATIBLE_NEWER")

    def test_config_v3_rejects_excludes_that_overlap_canonical_memory(self) -> None:
        for pattern in (
            "docs/memory/**",
            "docs\\memory\\**\\*.md",
            "docs/**",
            ".knowledge/private-memory/l0/**/*.md",
            ".knowledge/**",
        ):
            config = config_v3()
            config["documents"]["exclude"] = [pattern]
            self.assertTrue(
                any("canonical memory path" in error for error in memory_policy.validate_config_v3(config)),
                pattern,
            )
        config = config_v3()
        config["documents"]["exclude"] = ["docs/archive/**"]
        self.assertEqual(memory_policy.validate_config_v3(config), [])

    def test_l0_and_legacy_private_memory_are_hard_denied(self) -> None:
        with self.assertRaises(memory_policy.MemoryPolicyError) as caught:
            memory_policy.assert_memory_mutation_allowed(
                ".knowledge/private-memory/l0/raw.md",
                approved_targets=[".knowledge/private-memory/l0/raw.md"],
            )
        self.assertEqual(caught.exception.code, "L0_HARD_DENY")
        with self.assertRaises(memory_policy.MemoryPolicyError) as caught:
            memory_policy.assert_memory_mutation_allowed(
                ".knowledge/private-memory/l2/context.md",
                approved_targets=[".knowledge/private-memory/l2/context.md"],
            )
        self.assertEqual(caught.exception.code, "LEGACY_PRIVATE_MEMORY_HARD_DENY")
        self.assertEqual(
            memory_policy.assert_memory_mutation_allowed(
                "docs/memory/l1/shared.md",
                approved_targets=["docs/memory/l1/shared.md"],
            ),
            "docs/memory/l1/shared.md",
        )

    def test_approval_ids_are_exact_unique_and_known(self) -> None:
        self.assertEqual(
            memory_policy.validate_approved_ids(["MEMORY-B", "MEMORY-A"], ["MEMORY-A", "MEMORY-B"]),
            ("MEMORY-A", "MEMORY-B"),
        )
        for values, code in [
            ([], "MEMORY_APPROVAL_REQUIRED"),
            (["MEMORY-A", "MEMORY-A"], "DUPLICATE_MEMORY_APPROVAL"),
            (["MEMORY-X"], "UNKNOWN_MEMORY_APPROVAL"),
        ]:
            with self.assertRaises(memory_policy.MemoryPolicyError) as caught:
                memory_policy.validate_approved_ids(values, ["MEMORY-A"])
            self.assertEqual(caught.exception.code, code)


class SharedCopyTests(unittest.TestCase):
    def test_render_preserves_parsed_body_leading_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.md"
            target = root / "target.md"
            metadata = record("MEMORY-L1-BODY", work="body", source="body")["metadata"]
            body = "    indented code\n\n  trailing context\n"
            source.write_text(
                memory_policy.render_memory_document(metadata, body), encoding="utf-8"
            )
            parsed_metadata, parsed_body, _ = memory_policy._parse_memory_file(source)
            target.write_text(
                memory_policy.render_memory_document(parsed_metadata, parsed_body),
                encoding="utf-8",
            )
            _, target_body, _ = memory_policy._parse_memory_file(target)
            self.assertEqual(parsed_body, body)
            self.assertEqual(
                memory_policy.body_sha256(parsed_body), memory_policy.body_sha256(target_body)
            )
    def test_shared_copy_preserves_id_and_body_and_externalizes_l0(self) -> None:
        metadata = {
            "id": "MEMORY-L2-EXAMPLE-001",
            "type": "memory",
            "status": "active",
            "relations": [
                {"type": "distilled_from", "target": "MEMORY-L0-RAW-001"},
                {"type": "distilled_from", "target": "MEMORY-L1-SHARED-001"},
            ],
            "memory": {"level": "l2", "subject": "old-topic", "confidence": 1.0},
            "access": {
                "visibility": "private",
                "owner": "user:owner",
                "team": "team:repository",
                "grants": [],
            },
        }
        body = "# 한국어 본문\n\n원문 의미를 보존한다.\n"
        converted = memory_policy.build_shared_copy(
            metadata,
            body,
            approval={
                "subject": "team:repository",
                "scope": "team",
                "claim_key": "workflow.handoff",
                "claim_value": "shared-context",
                "sharing": sharing("two", "opaque:two"),
            },
            local_l0_ids=["MEMORY-L0-RAW-001"],
            allowed_shared_ids=["MEMORY-L1-SHARED-001"],
        )
        self.assertEqual(converted["metadata"]["id"], metadata["id"])
        self.assertEqual(converted["body"], body)
        self.assertEqual(converted["body_sha256"], memory_policy.body_sha256(body))
        self.assertEqual(
            converted["relation_after"],
            [{"type": "distilled_from", "target": "MEMORY-L1-SHARED-001"}],
        )
        self.assertEqual(converted["relation_mapping"][0]["action"], "externalized-local-l0")

    def test_l3_copy_always_starts_proposed(self) -> None:
        source = record("PERSONA-OLD-001", level="l3", work="one", source="install:one")
        converted = memory_policy.build_shared_copy(
            source["metadata"],
            "# Persona\n",
            approval={"sharing": sharing("one", "install:one")},
        )
        self.assertEqual(converted["metadata"]["status"], "proposed")
        self.assertEqual(converted["metadata"]["sharing"]["approved_by"], [])
        self.assertIsNone(converted["metadata"]["sharing"]["approved_at"])

    def test_plan_and_stage_are_deterministic_and_do_not_touch_l0(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            l0_dir = root / ".knowledge" / "private-memory" / "l0"
            l1_dir = root / ".knowledge" / "private-memory" / "l1"
            l0_dir.mkdir(parents=True)
            l1_dir.mkdir(parents=True)
            l0 = {
                "id": "MEMORY-L0-RAW-001",
                "type": "memory",
                "status": "active",
                "memory": {"level": "l0"},
            }
            legacy = {
                "id": "MEMORY-L1-EXAMPLE-001",
                "type": "memory",
                "status": "active",
                "relations": [{"type": "distilled_from", "target": "MEMORY-L0-RAW-001"}],
                "memory": {"level": "l1", "subject": "legacy-topic", "confidence": 1.0},
                "access": {
                    "visibility": "private",
                    "owner": "user:owner",
                    "team": "team:repository",
                    "grants": [],
                },
            }
            (l0_dir / "raw.md").write_text(
                memory_policy.render_memory_document(l0, "# raw\n"), encoding="utf-8"
            )
            (l1_dir / "fact.md").write_text(
                memory_policy.render_memory_document(legacy, "# 사실\n"), encoding="utf-8"
            )
            approval = {
                "subject": "user:owner",
                "scope": "personal",
                "kind": "preference",
                "claim_key": "workflow.example",
                "claim_value": "yes",
                "sharing": sharing("one", "install:one"),
                "sensitivity_review": {
                    "decision": "share",
                    "reviewed_by": "user:owner",
                    "reviewed_at": "2026-08-08T00:00:00Z",
                    "checks": ["secrets", "third_party_pii", "local_paths", "device_names"],
                },
            }
            old_l0 = (l0_dir / "raw.md").read_bytes()
            plan = memory_policy.plan_memory_layout(
                root,
                {"version": 2, "memory": {}},
                ["MEMORY-L1-EXAMPLE-001"],
                approvals={"MEMORY-L1-EXAMPLE-001": approval},
            )
            repeated = memory_policy.plan_memory_layout(
                root,
                {"version": 2, "memory": {}},
                ["MEMORY-L1-EXAMPLE-001"],
                approvals={"MEMORY-L1-EXAMPLE-001": approval},
            )
            self.assertEqual(plan["aggregate_lineage_digest"], repeated["aggregate_lineage_digest"])
            action = plan["actions"][0]
            self.assertEqual(action["target_path"], "docs/memory/l1/fact.md")
            self.assertEqual(action["relation_after"], [])
            stage = root / ".knowledge" / "upgrade-backups" / "tx" / "memory-staging"
            staged = memory_policy.apply_memory_layout(plan, stage)
            self.assertEqual(len(staged), 1)
            self.assertTrue((stage / "docs" / "memory" / "l1" / "fact.md").is_file())
            self.assertEqual((l0_dir / "raw.md").read_bytes(), old_l0)

    def test_legacy_dispositions_are_safe_and_only_share_targets_are_approvable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy_root = root / ".knowledge" / "private-memory" / "l1"
            legacy_root.mkdir(parents=True)

            blocked = record("MEMORY-PRIVATE", work="private", source="private")["metadata"]
            blocked["access"]["visibility"] = "private"
            blocked["memory"]["subject"] = "legacy-private-slug"
            blocked["memory"].pop("claim_key")
            blocked["memory"].pop("claim_value")
            blocked.pop("sharing")
            review = copy.deepcopy(blocked)
            review["id"] = "MEMORY-REVIEW"
            review["access"]["visibility"] = "team"
            share = record("MEMORY-SHARE", work="share", source="share")["metadata"]
            for name, metadata, body in (
                ("blocked.md", blocked, "private body must not appear\n"),
                ("review.md", review, "review body must not appear\n"),
                ("share.md", share, "canonical body must not appear\n"),
            ):
                (legacy_root / name).write_text(
                    memory_policy.render_memory_document(metadata, body), encoding="utf-8"
                )

            inventory = memory_policy.plan_memory_layout(
                root, {"version": 2, "memory": {}}, []
            )
            by_id = {item["id"]: item for item in inventory["dispositions"]}
            self.assertEqual(by_id["MEMORY-PRIVATE"]["disposition"], "blocked_sensitive")
            self.assertEqual(by_id["MEMORY-PRIVATE"]["subject_candidate"], "user:owner")
            self.assertEqual(by_id["MEMORY-REVIEW"]["disposition"], "needs_claim_review")
            self.assertEqual(by_id["MEMORY-SHARE"]["disposition"], "share")
            self.assertEqual(inventory["approval_targets"], ["MEMORY-SHARE"])
            public = copy.deepcopy(inventory)
            public.pop("eligible_actions")
            serialized = yaml.safe_dump(public, allow_unicode=True)
            self.assertNotIn("private body must not appear", serialized)
            self.assertNotIn(str(legacy_root), serialized)

            weak_review = memory_policy.plan_memory_layout(
                root,
                {"version": 2, "memory": {}},
                [],
                approvals={"MEMORY-PRIVATE": {"subject": "user:owner"}},
            )
            weak_by_id = {item["id"]: item for item in weak_review["dispositions"]}
            self.assertEqual(weak_by_id["MEMORY-PRIVATE"]["disposition"], "blocked_sensitive")

            with self.assertRaises(memory_policy.MemoryPolicyError) as caught:
                memory_policy.plan_memory_layout(
                    root, {"version": 2, "memory": {}}, ["MEMORY-REVIEW"]
                )
            self.assertEqual(caught.exception.code, "MEMORY_REVIEW_REQUIRED")
            approved = memory_policy.plan_memory_layout(
                root, {"version": 2, "memory": {}}, ["MEMORY-SHARE"]
            )
            self.assertEqual([item["memory_id"] for item in approved["actions"]], ["MEMORY-SHARE"])


class L3CandidateTests(unittest.TestCase):
    def test_l3_activation_requires_explicit_authorized_approval(self) -> None:
        first = record("MEMORY-L1-A", work="one", source="raw-one")
        second = record("MEMORY-L1-B", work="two", source="raw-two")
        proposal = record(
            "PERSONA-A", level="l3", work="persona", source="persona", status="proposed"
        )["metadata"]
        proposal["relations"] = [
            {"type": "distilled_from", "target": "MEMORY-L1-A"},
            {"type": "distilled_from", "target": "MEMORY-L1-B"},
        ]
        proposal["sharing"]["approved_by"] = []
        proposal["sharing"]["approved_at"] = None
        by_id = {
            "MEMORY-L1-A": first,
            "MEMORY-L1-B": second,
            "PERSONA-A": {"metadata": proposal},
        }
        proposal["sharing"]["evidence_digest"] = memory_policy.evidence_digest_for_metadata(
            proposal, by_id
        )
        activated = memory_policy.approve_l3(
            proposal,
            approver="user:owner",
            approved_at="2026-08-08T00:00:00Z",
            config={
                **config_v3(),
                "access_control": {"managers": ["user:owner"]},
            },
            by_id=by_id,
        )
        self.assertEqual(activated["status"], "active")
        self.assertEqual(activated["sharing"]["approved_by"], ["user:owner"])
        self.assertEqual(proposal["status"], "proposed")
        with self.assertRaises(memory_policy.MemoryPolicyError) as caught:
            memory_policy.approve_l3(
                proposal,
                approver="user:reviewer",
                approved_at="2026-08-08T00:00:00Z",
                config={**config_v3(), "access_control": {"managers": ["user:owner"]}},
                by_id=by_id,
            )
        self.assertEqual(caught.exception.code, "L3_APPROVAL_REJECTED")

    def test_l3_activation_rejects_insufficient_conflict_covered_and_stale(self) -> None:
        config = {**config_v3(), "access_control": {"managers": ["user:owner"]}}

        def proposal_for(parents: list[dict], *, value: str = "skill-over-hook") -> tuple[dict, dict]:
            proposal = record(
                "PERSONA-PROPOSED", level="l3", work="persona", source="persona",
                value=value, status="proposed",
            )["metadata"]
            proposal["relations"] = [
                {"type": "distilled_from", "target": item["metadata"]["id"]}
                for item in parents
            ]
            proposal["sharing"]["approved_by"] = []
            proposal["sharing"]["approved_at"] = None
            by_id = {item["metadata"]["id"]: item for item in parents}
            by_id[proposal["id"]] = {"metadata": proposal}
            proposal["sharing"]["evidence_digest"] = memory_policy.evidence_digest_for_metadata(
                proposal, by_id
            )
            return proposal, by_id

        one = record("MEMORY-ONE", work="one", source="one")
        proposal, by_id = proposal_for([one])
        with self.assertRaises(memory_policy.MemoryPolicyError) as caught:
            memory_policy.approve_l3(
                proposal, approver="user:owner", approved_at="2026-08-08T00:00:00Z",
                config=config, by_id=by_id,
            )
        self.assertEqual(caught.exception.code, "L3_NOT_ELIGIBLE")

        proposal, by_id = proposal_for([one])
        prior = record("PERSONA-PRIOR", level="l3", work="prior", source="prior")
        prior["metadata"]["relations"] = [
            {"type": "distilled_from", "target": "MEMORY-NO-LONGER-ACTIVE"}
        ]
        by_id[prior["metadata"]["id"]] = prior
        group = memory_policy.l3_candidate_groups(list(by_id.values()))[0]
        self.assertEqual(group["status"], "update_eligible")
        self.assertEqual(group["evidence_count"], 1)
        with self.assertRaises(memory_policy.MemoryPolicyError) as caught:
            memory_policy.approve_l3(
                proposal, approver="user:owner", approved_at="2026-08-08T00:00:00Z",
                config=config, by_id=by_id,
            )
        self.assertEqual(caught.exception.code, "L3_NOT_ELIGIBLE")

        same = record("MEMORY-SAME", work="same", source="same")
        conflicting = record("MEMORY-CONFLICT", work="conflict", source="conflict", value="hook")
        proposal, by_id = proposal_for([one, same])
        by_id[conflicting["metadata"]["id"]] = conflicting
        with self.assertRaises(memory_policy.MemoryPolicyError) as caught:
            memory_policy.approve_l3(
                proposal, approver="user:owner", approved_at="2026-08-08T00:00:00Z",
                config=config, by_id=by_id,
            )
        self.assertEqual(caught.exception.code, "L3_NOT_ELIGIBLE")

        proposal, by_id = proposal_for([one, same])
        active = record(
            "PERSONA-ACTIVE", level="l3", work="active", source="active"
        )
        active["metadata"]["relations"] = copy.deepcopy(proposal["relations"])
        by_id[active["metadata"]["id"]] = active
        with self.assertRaises(memory_policy.MemoryPolicyError) as caught:
            memory_policy.approve_l3(
                proposal, approver="user:owner", approved_at="2026-08-08T00:00:00Z",
                config=config, by_id=by_id,
            )
        self.assertEqual(caught.exception.code, "L3_NOT_ELIGIBLE")

        proposal, by_id = proposal_for([one, same])
        proposal["sharing"]["evidence_digest"] = ZERO_HASH
        with self.assertRaises(memory_policy.MemoryPolicyError) as caught:
            memory_policy.approve_l3(
                proposal, approver="user:owner", approved_at="2026-08-08T00:00:00Z",
                config=config, by_id=by_id,
            )
        self.assertEqual(caught.exception.code, "L3_STALE_EVIDENCE")

    def test_l3_activation_requires_exact_canonical_evidence_ids(self) -> None:
        first = record("MEMORY-FIRST", work="first", source="first")
        second = record("MEMORY-SECOND", work="second", source="second")
        proposal = record(
            "PERSONA-SUBSET", level="l3", work="persona", source="persona", status="proposed"
        )["metadata"]
        proposal["relations"] = [{"type": "distilled_from", "target": "MEMORY-FIRST"}]
        proposal["sharing"]["approved_by"] = []
        proposal["sharing"]["approved_at"] = None
        by_id = {
            "MEMORY-FIRST": first,
            "MEMORY-SECOND": second,
            "PERSONA-SUBSET": {"metadata": proposal},
        }
        proposal["sharing"]["evidence_digest"] = memory_policy.evidence_digest_for_metadata(
            proposal, by_id
        )
        with self.assertRaises(memory_policy.MemoryPolicyError) as caught:
            memory_policy.approve_l3(
                proposal,
                approver="user:owner",
                approved_at="2026-08-08T00:00:00Z",
                config={**config_v3(), "access_control": {"managers": ["user:owner"]}},
                by_id=by_id,
            )
        self.assertEqual(caught.exception.code, "L3_EVIDENCE_MISMATCH")

    def test_two_independent_work_units_and_provenance_are_eligible(self) -> None:
        records = [
            record("MEMORY-L1-A", work="one", source="install-one:raw-one"),
            record("MEMORY-L1-B", work="two", source="install-two:raw-two"),
        ]
        result = memory_policy.l3_candidate_groups(records)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "eligible")
        self.assertEqual(result[0]["evidence_count"], 2)

    def test_same_work_or_same_top_provenance_counts_once(self) -> None:
        same_work = [
            record("MEMORY-L1-A", work="one", source="raw-one"),
            record("MEMORY-L1-B", work="one", source="raw-two"),
        ]
        same_source = [
            record("MEMORY-L1-A", work="one", source="raw-one"),
            record("MEMORY-L1-B", work="two", source="raw-one"),
        ]
        self.assertEqual(memory_policy.l3_candidate_groups(same_work)[0]["evidence_count"], 1)
        self.assertEqual(memory_policy.l3_candidate_groups(same_source)[0]["evidence_count"], 1)

    def test_l1_and_derived_l2_from_same_l0_are_not_double_counted(self) -> None:
        l1 = record("MEMORY-L1-A", work="one", source="raw-one")
        l2 = record("MEMORY-L2-A", level="l2", work="two", source="raw-two", parent="MEMORY-L1-A")
        result = memory_policy.l3_candidate_groups([l1, l2])[0]
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["evidence_count"], 1)

    def test_diamond_lineage_counts_one_top_level_provenance(self) -> None:
        root = record("MEMORY-ROOT", work="root", source="root")
        left = record("MEMORY-LEFT", level="l2", work="left", source="left", parent="MEMORY-ROOT")
        right = record("MEMORY-RIGHT", level="l2", work="right", source="right", parent="MEMORY-ROOT")
        diamond = record("MEMORY-DIAMOND", level="l2", work="diamond", source="diamond")
        diamond["metadata"]["relations"] = [
            {"type": "distilled_from", "target": "MEMORY-LEFT"},
            {"type": "distilled_from", "target": "MEMORY-RIGHT"},
        ]
        result = memory_policy.l3_candidate_groups([root, left, right, diamond])[0]
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["evidence_count"], 1)

    def test_conflict_is_separate_from_unrelated_claims(self) -> None:
        records = [
            record("MEMORY-L1-A", work="one", source="raw-one", value="skill"),
            record("MEMORY-L1-B", work="two", source="raw-two", value="hook"),
            record("MEMORY-L1-C", work="three", source="raw-three", value="skill"),
        ]
        unrelated = copy.deepcopy(record("MEMORY-L1-D", work="four", source="raw-four"))
        unrelated["metadata"]["memory"]["claim_key"] = "workflow.unrelated"
        result = memory_policy.l3_candidate_groups([*records, unrelated])
        conflicted = [item for item in result if item["claim_key"] == "workflow.context-aware-automation"]
        self.assertTrue(all(item["status"] == "conflict" for item in conflicted))
        self.assertEqual(
            [item for item in result if item["claim_key"] == "workflow.unrelated"][0]["status"],
            "insufficient_evidence",
        )

    def test_active_l3_reports_covered_then_update_eligible(self) -> None:
        l1 = record("MEMORY-L1-A", work="one", source="raw-one")
        l2 = record("MEMORY-L1-B", work="two", source="raw-two")
        persona = record(
            "PERSONA-A", level="l3", work="persona", source="persona", parent="MEMORY-L1-A"
        )
        persona["metadata"]["relations"].append(
            {"type": "distilled_from", "target": "MEMORY-L1-B"}
        )
        self.assertEqual(
            memory_policy.l3_candidate_groups([l1, l2, persona])[0]["status"], "covered"
        )
        l3 = record("MEMORY-L1-C", work="three", source="raw-three")
        self.assertEqual(
            memory_policy.l3_candidate_groups([l1, l2, l3, persona])[0]["status"],
            "update_eligible",
        )


if __name__ == "__main__":
    unittest.main()
