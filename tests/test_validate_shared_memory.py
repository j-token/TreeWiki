from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "treewiki" / "scripts"
VALIDATOR = SCRIPTS / "validate_knowledge.py"
sys.path.insert(0, str(SCRIPTS))

import memory_policy  # noqa: E402


ZERO_HASH = "sha256:" + "0" * 64


class SharedMemoryValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / ".knowledge").mkdir()
        vocabulary = self.root / "docs" / "vocabulary"
        vocabulary.mkdir(parents=True)
        (vocabulary / "topics.yml").write_text(
            "memory-governance:\n  label: Memory governance\n  aliases: []\n", encoding="utf-8"
        )
        (vocabulary / "glossary.yml").write_text("terms: []\n", encoding="utf-8")
        self.config = {
            "version": 4,
            "documents": {
                "include": ["docs/**/*.md", ".knowledge/private-memory/l0/**/*.md"],
                "exclude": [],
            },
            "vocabulary_path": "docs/vocabulary/topics.yml",
            "glossary_path": "docs/vocabulary/glossary.yml",
            "memory": {
                "layout_version": 2,
                "capture": "explicit",
                "private_path": ".knowledge/private-memory",
                "shared_path": "docs/memory",
                "persona_requires_sources": 2,
                "l3": {
                    "knowledge_path": "docs/memory/l3/knowledge",
                    "persona_path": "docs/memory/l3/persona",
                },
            },
            "history": {"schema": 1, "sidecar": "stable-id"},
            "hooks": {"enabled": False, "l3": {"minimum_sources": 2}},
            "access_control": {
                "default_owner": "user:owner",
                "default_team": "team:repository",
                "managers": ["user:owner"],
            },
            "retrieval": {"bm25_index_path": ".knowledge/index/search.db"},
        }
        self.write_config()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_config(self) -> None:
        (self.root / ".knowledge" / "config.yml").write_text(
            yaml.safe_dump(self.config, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    def sharing(self, *, approved: bool = True) -> dict:
        return {
            "authored_by": "agent:treewiki",
            "shared_by": ["user:owner"],
            "shared_at": "2026-08-08T00:00:00Z",
            "approved_by": ["user:owner"] if approved else [],
            "approved_at": "2026-08-08T00:00:00Z" if approved else None,
            "evidence_digest": ZERO_HASH,
            "source_ref": "local-memory:install-opaque:work-opaque",
            "source_hash": ZERO_HASH,
            "source_machine": "install:opaque",
            "work_unit_id": "work:opaque",
        }

    def metadata(self, doc_id: str, *, level: str = "l1", status: str = "active") -> dict:
        return {
            "id": doc_id,
            "title": "공유 기억",
            "type": "persona" if level == "l3" else "memory",
            "status": status,
            "authority": "informative",
            "topics": ["memory-governance"],
            "summary": "공유 기억 검증 fixture다.",
            "relations": [],
            "reviewed": "2026-08-08",
            "memory": {
                "level": level,
                "subject": "user:owner",
                "kind": "preference",
                "scope": "user",
                "claim_key": "workflow.example",
                "claim_value": "preferred",
                "confidence": 1.0,
            },
            "access": {
                "visibility": "team",
                "owner": "user:owner",
                "team": "team:repository",
                "grants": [],
            },
            "sharing": self.sharing(approved=status == "active"),
            "embedding": {"mode": "local_only", "content": "full"},
        }

    def write_memory(self, metadata: dict, name: str | None = None) -> Path:
        level = metadata["memory"]["level"]
        directory = self.root / "docs" / "memory" / level
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (name or f"{metadata['id'].lower()}.md")
        path.write_text(
            memory_policy.render_memory_document(metadata, f"# {metadata['title']}\n"),
            encoding="utf-8",
        )
        return path

    def validate(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(self.root)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def test_l0_absent_clone_accepts_complete_shared_l1(self) -> None:
        self.write_memory(self.metadata("MEMORY-L1-SHARED-001"))
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Validated 1 documents: 0 errors", result.stdout)

    def test_all_sharing_fields_are_required_and_opaque(self) -> None:
        metadata = self.metadata("MEMORY-L1-SHARED-001")
        del metadata["sharing"]["source_machine"]
        metadata["sharing"]["source_ref"] = "C:\\Users\\owner\\conversation.md"
        self.write_memory(metadata)
        result = self.validate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sharing.source_ref must be an opaque", result.stdout)
        self.assertIn("sharing.source_machine must be an opaque", result.stdout)

    def test_proposed_l3_has_no_activation_approval(self) -> None:
        metadata = self.metadata("PERSONA-SHARED-001", level="l3", status="proposed")
        self.write_memory(metadata)
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        metadata["sharing"]["approved_by"] = ["user:owner"]
        self.write_memory(metadata)
        result = self.validate()
        self.assertIn("proposed L3 must use approved_by: []", result.stdout)

    def test_active_l3_requires_approver_and_current_evidence_digest(self) -> None:
        first = self.metadata("MEMORY-L1-A")
        second = self.metadata("MEMORY-L1-B")
        self.write_memory(first)
        self.write_memory(second)
        persona = self.metadata("PERSONA-A", level="l3")
        persona["relations"] = [
            {"type": "distilled_from", "target": first["id"]},
            {"type": "distilled_from", "target": second["id"]},
        ]
        by_id = {
            first["id"]: {"metadata": first},
            second["id"]: {"metadata": second},
            persona["id"]: {"metadata": persona},
        }
        persona["sharing"]["evidence_digest"] = memory_policy.evidence_digest_for_metadata(
            persona, by_id
        )
        self.write_memory(persona)
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        stale = copy.deepcopy(persona)
        stale["sharing"]["evidence_digest"] = ZERO_HASH
        self.write_memory(stale)
        result = self.validate()
        self.assertIn("evidence_digest is stale", result.stdout)

    def test_config_v4_rejects_private_l1_and_broad_private_glob(self) -> None:
        self.config["documents"]["include"].append(".knowledge/private-memory/**/*.md")
        self.write_config()
        metadata = self.metadata("MEMORY-L1-PRIVATE-001")
        private = self.root / ".knowledge" / "private-memory" / "l1"
        private.mkdir(parents=True)
        (private / "legacy.md").write_text(
            memory_policy.render_memory_document(metadata, "# legacy\n"), encoding="utf-8"
        )
        result = self.validate()
        self.assertIn("must not include private L1-L3", result.stdout)
        self.assertIn("current config permits only L0", result.stdout)


if __name__ == "__main__":
    unittest.main()
