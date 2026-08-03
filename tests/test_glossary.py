from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "lmwiki" / "scripts"


class GlossaryTests(unittest.TestCase):
    def bootstrap(self, repository: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "bootstrap_lmwiki.py"),
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


if __name__ == "__main__":
    unittest.main()
