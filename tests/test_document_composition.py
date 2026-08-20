from __future__ import annotations

import sys
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "treewiki" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from document_composition import (  # noqa: E402
    composition_limits,
    document_composition_messages,
)
from governance_report import build_governance_report  # noqa: E402
from validate_knowledge import managed_documents  # noqa: E402


class DocumentCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.limits, errors = composition_limits({})
        self.assertEqual(errors, [])

    def test_body_at_target_is_valid(self) -> None:
        errors, warnings = document_composition_messages(
            {}, "\n".join(["line"] * 50), limits=self.limits
        )
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_body_over_target_warns_with_split_structure(self) -> None:
        errors, warnings = document_composition_messages(
            {}, "\n".join(["line"] * 51), limits=self.limits
        )
        self.assertEqual(errors, [])
        self.assertIn("directory with an AGENTS.md map", warnings[0])

    def test_body_over_hard_limit_is_rejected(self) -> None:
        errors, warnings = document_composition_messages(
            {}, "\n".join(["line"] * 81), limits=self.limits
        )
        self.assertIn("composition hard limit", errors[0])
        self.assertEqual(warnings, [])

    def test_token_heavy_short_body_is_rejected(self) -> None:
        errors, _ = document_composition_messages(
            {}, "x" * 4001, limits=self.limits
        )
        self.assertIn("about 1001 tokens", errors[0])

    def test_non_empty_exception_suppresses_budget_messages(self) -> None:
        metadata = {"composition": {"size_exception": "API table must remain contiguous."}}
        errors, warnings = document_composition_messages(
            metadata, "\n".join(["line"] * 81), limits=self.limits
        )
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_invalid_limits_and_exception_are_rejected(self) -> None:
        _, config_errors = composition_limits({
            "composition": {"body_line_target": 80, "body_line_hard_limit": 50}
        })
        self.assertIn("greater than or equal", config_errors[0])
        errors, _ = document_composition_messages(
            {"composition": {"size_exception": ""}}, "body", limits=self.limits
        )
        self.assertIn("non-empty reason", errors[0])

    def test_repository_validation_enforces_the_hard_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".knowledge").mkdir()
            (root / ".knowledge" / "config.yml").write_text(
                "version: 3\n"
                "documents:\n"
                "  include: ['docs/**/*.md']\n"
                "  exclude: []\n"
                "vocabulary_path: docs/vocabulary/topics.yml\n"
                "glossary_path: docs/vocabulary/glossary.yml\n",
                encoding="utf-8",
            )
            vocabulary = root / "docs" / "vocabulary"
            vocabulary.mkdir(parents=True)
            (vocabulary / "topics.yml").write_text(
                "test:\n  label: Test\n  aliases: []\n", encoding="utf-8"
            )
            (vocabulary / "glossary.yml").write_text("terms: []\n", encoding="utf-8")
            (root / "docs" / "long.md").write_text(
                "---\n"
                "id: TEST-LONG-001\n"
                "title: Long document\n"
                "type: concept\n"
                "status: draft\n"
                "authority: informative\n"
                "topics: [test]\n"
                "summary: Long document fixture.\n"
                "relations: []\n"
                "reviewed: 2026-08-20\n"
                "---\n\n"
                + "\n".join(["line"] * 81)
                + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_knowledge.py"), str(root)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("body exceeds composition hard limit", result.stdout)

    def test_governance_report_surfaces_composition_review(self) -> None:
        report = build_governance_report(Path.cwd(), [{
            "path": "docs/long.md",
            "body": "\n".join(["line"] * 51),
            "metadata": {"id": "TEST-LONG-001", "relations": []},
        }])
        finding = next(item for item in report["findings"] if item["kind"] == "document_composition")
        self.assertEqual(finding["severity"], "warning")
        self.assertIn("target 50", finding["message"])

    def test_operational_skill_backups_are_never_managed_documents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root_map = root / "AGENTS.md"
            root_map.write_text("root\n", encoding="utf-8")
            backup = root / ".agents" / "skills" / ".treewiki-backups" / "tx" / "AGENTS.md"
            backup.parent.mkdir(parents=True)
            backup.write_text("backup\n", encoding="utf-8")
            documents = managed_documents(root, {
                "documents": {"include": ["**/AGENTS.md"], "exclude": []}
            })
            self.assertEqual(documents, [root_map])


if __name__ == "__main__":
    unittest.main()
