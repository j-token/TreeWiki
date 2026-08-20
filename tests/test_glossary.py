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


class GlossaryTests(unittest.TestCase):
    def bootstrap(self, repository: Path) -> None:
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
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def finalize(self, repository: Path, relative_path: str, document_id: str) -> None:
        base = [
            sys.executable,
            str(SCRIPTS / "knowledge_cli.py"),
            "manage",
            "document-finalize",
            str(repository),
            "--path",
            relative_path,
            "--created-id",
            document_id,
            "--principal",
            "user:owner",
            "--team",
            "team:repository",
        ]
        planned = subprocess.run(
            base, check=False, capture_output=True, text=True, encoding="utf-8"
        )
        self.assertEqual(planned.returncode, 0, planned.stdout + planned.stderr)
        plan_id = next(
            line.removeprefix("PLAN ID ")
            for line in planned.stdout.splitlines()
            if line.startswith("PLAN ID ")
        )
        applied = subprocess.run(
            [*base, "--plan-id", plan_id, "--apply"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

    def test_query_glossary_returns_term_and_description(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            self.bootstrap(repository)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "knowledge_cli.py"),
                    "query",
                    "glossary",
                    str(repository),
                    "용어집",
                    "--json",
                    "--principal",
                    "user:owner",
                    "--team",
                    "team:repository",
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            item = json.loads(result.stdout)
            self.assertEqual(item["term"], "용어집")
            self.assertTrue(item["description"])

    def test_validation_rejects_duplicate_and_incomplete_terms(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            self.bootstrap(repository)
            glossary_path = repository / "docs" / "vocabulary" / "glossary.yml"
            glossary_path.write_text(
                yaml.safe_dump(
                    {
                        "terms": [
                            {"term": "Workspace", "description": "작업 공간"},
                            {"term": " workspace ", "description": "중복"},
                            {"term": "설명 없음", "description": ""},
                        ]
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
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
            self.assertEqual(result.returncode, 1)
            self.assertIn("duplicate term", result.stdout)
            self.assertIn("description must be a non-empty string", result.stdout)

    def test_glossary_candidates_reports_declared_unregistered_terms(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            self.bootstrap(repository)
            document = repository / "docs" / "concepts" / "memory-core.md"
            document.parent.mkdir(parents=True, exist_ok=True)
            document.write_text(
                "---\n"
                "id: CONCEPT-MEMORY-CORE-001\n"
                "title: Memory Core\n"
                "type: concept\nstatus: active\nauthority: informative\n"
                "topics: [repository-knowledge-management]\n"
                "summary: 기억 계층을 관리한다.\nrelations: []\n"
                "reviewed: 2026-08-04\n"
                "governance:\n"
                "  owner: user:owner\n"
                "  reviewers: [user:owner]\n"
                "  review_cadence_days: 90\n"
                "  source_of_truth: AGENTS.md\n"
                "  last_source_check: 2026-08-04\n"
                "  duplicate_of: null\n"
                "  retirement_reason: null\n"
                "  scope: domain\n"
                "  domain: repository\n"
                "glossary_terms: [용어집, Memory Core]\n"
                "---\n\n# Memory Core\n",
                encoding="utf-8",
            )
            self.finalize(
                repository, "docs/concepts/memory-core.md", "CONCEPT-MEMORY-CORE-001"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "knowledge_cli.py"),
                    "query",
                    "glossary-candidates",
                    str(repository),
                    "--json",
                    "--principal",
                    "user:owner",
                    "--team",
                    "team:repository",
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('"term":"Memory Core"', result.stdout)
            self.assertNotIn('"term":"용어집"', result.stdout)

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
            self.assertIn("unregistered glossary term 'Memory Core'", validation.stdout)


if __name__ == "__main__":
    unittest.main()
