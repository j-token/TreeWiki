from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "treewiki" / "scripts"
CLI = SCRIPTS / "knowledge_cli.py"
BOOTSTRAP = SCRIPTS / "bootstrap_treewiki.py"
sys.path.insert(0, str(SCRIPTS))

from code_context import build_context_plan  # noqa: E402
from governance_report import build_governance_report  # noqa: E402
from retrieval_gaps import append_gap, folded_report, plan_gap, read_events  # noqa: E402
from technical_writing import REQUIRED_SECTIONS, technical_document_messages, template_body  # noqa: E402


class TechnicalWritingTests(unittest.TestCase):
    def test_every_technical_template_satisfies_required_sections(self) -> None:
        for doc_type in REQUIRED_SECTIONS:
            metadata = {
                "type": doc_type,
                "status": "draft",
                "technical_writing": True,
                "context": {},
                "governance": {},
            }
            errors, warnings = technical_document_messages(metadata, template_body(doc_type, "Example"))
            self.assertEqual(errors, [], doc_type)
            self.assertEqual(warnings, [], doc_type)

    def test_missing_section_is_rejected_and_active_placeholder_warns(self) -> None:
        metadata = {
            "type": "how_to",
            "status": "active",
            "context": {},
            "governance": {},
        }
        body = template_body("how_to", "Example").replace("## Sources\n[TODO]\n", "")
        errors, warnings = technical_document_messages(metadata, body)
        self.assertIn("how_to requires section 'Sources'", errors)
        self.assertIn("active technical document still contains placeholder text", warnings)

    def test_retrieval_gap_plan_is_deduplicated_and_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "retrieval-gaps.jsonl"
            plan = plan_gap(
                query="missing policy", principal="user:test", team="team:repo",
                reason="no_result", work_unit="work-1",
            )
            self.assertNotIn("document_title", plan)
            self.assertNotIn("document_body", plan)
            first = append_gap(path, plan, plan_id=plan["plan_id"])
            second = append_gap(path, plan, plan_id=plan["plan_id"])
            self.assertEqual(first["status"], "APPLIED")
            self.assertEqual(second["status"], "DEDUPED")
            resolved = plan_gap(
                query="missing policy", principal="user:test", team="team:repo",
                reason="no_result", work_unit="work-1", status="resolved",
                resolution_document_id="DOC-1",
            )
            append_gap(path, resolved, plan_id=resolved["plan_id"])
            report = folded_report(read_events(path), principal="user:test")
            self.assertEqual(report[0]["status"], "resolved")
            self.assertEqual(report[0]["resolution_document_id"], "DOC-1")

    def test_code_context_plan_is_deterministic_and_ignores_unselected_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repository), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repository), "config", "user.name", "Test"], check=True)
            (repository / "selected.py").write_text("VALUE = 1\n", encoding="utf-8")
            (repository / "other.py").write_text("OTHER = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repository), "commit", "-m", "fixture"], check=True, capture_output=True)
            commit = subprocess.run(
                ["git", "-C", str(repository), "rev-parse", "HEAD"], check=True,
                capture_output=True, text=True, encoding="utf-8",
            ).stdout.strip()
            first = build_context_plan(
                repository, commit=commit, paths=["selected.py"], symbols=["VALUE"],
                owner="user:test", team="team:repo",
            )
            (repository / "other.py").write_text("OTHER = 2\n", encoding="utf-8")
            second = build_context_plan(
                repository, commit=commit, paths=["selected.py"], symbols=["VALUE"],
                owner="user:test", team="team:repo",
            )
            self.assertEqual(first["plan_id"], second["plan_id"])
            self.assertEqual(first["content_digest"], second["content_digest"])

            (repository / "selected.py").write_text("VALUE = 2\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repository), "add", "selected.py"], check=True)
            subprocess.run(["git", "-C", str(repository), "commit", "-m", "change selected"], check=True, capture_output=True)
            report = build_governance_report(repository, [{
                "path": "docs/reference.md",
                "body": "unique",
                "metadata": {
                    "id": "REF-1", "status": "active",
                    "context": {"source_commit": commit, "source_paths": ["selected.py"]},
                    "governance": {"last_source_check": "2020-01-01", "review_cadence_days": 1},
                    "relations": [],
                },
            }])
            kinds = {item["kind"] for item in report["findings"]}
            self.assertIn("source_stale", kinds)
            self.assertIn("overdue", kinds)

    def test_generate_context_apply_creates_a_valid_draft_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repository), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repository), "config", "user.name", "Test"], check=True)
            (repository / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repository), "add", "src.py"], check=True)
            subprocess.run(["git", "-C", str(repository), "commit", "-m", "fixture"], check=True, capture_output=True)
            bootstrapped = subprocess.run(
                [sys.executable, str(BOOTSTRAP), str(repository), "--embedding", "disabled", "--owner", "user:owner", "--team", "team:repo"],
                check=False, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(bootstrapped.returncode, 0, bootstrapped.stdout + bootstrapped.stderr)
            base = [
                sys.executable, str(CLI), "generate-context", str(repository), "--commit", "HEAD",
                "--path", "src.py", "--symbol", "VALUE", "--principal", "user:owner", "--team", "team:repo", "--json",
            ]
            planned = subprocess.run(base, check=False, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(planned.returncode, 0, planned.stdout + planned.stderr)
            import json
            plan = json.loads(planned.stdout)
            applied = subprocess.run(
                [*base, "--plan-id", plan["plan_id"], "--apply"], check=False,
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            target = repository / plan["path"]
            self.assertTrue(target.is_file())
            self.assertTrue(
                (repository / ".knowledge" / "document-history" / f"{plan['document_id']}.jsonl").is_file()
            )
            self.assertFalse(target.with_name(f"{plan['document_id']}.history.jsonl").exists())
            validation = subprocess.run(
                [sys.executable, str(CLI), "manage", "validate", str(repository)], check=False,
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)


if __name__ == "__main__":
    unittest.main()
