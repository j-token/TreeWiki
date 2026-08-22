from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "treewiki" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from treewiki_core import TreeWikiError, document_history, initialize, read, search, status, sync, validate  # noqa: E402


class TreeWikiV030Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        initialize(self.root)
        (self.root / "docs" / "policies").mkdir(parents=True)
        (self.root / "docs" / "decisions").mkdir(parents=True)
        (self.root / "AGENTS.md").write_text(
            "---\nid: MAP-ROOT\ntype: map\n---\n\n# Project map\n\n"
            "- [Policy](docs/policies/security.md)\n- [Decision](docs/decisions/index.md)\n",
            encoding="utf-8",
        )
        (self.root / "docs" / "policies" / "security.md").write_text(
            "---\nid: POLICY-SECURITY\ntype: policy\n---\n\n# 로컬 검색 정책\n\n"
            "검색 색인은 로컬에 둔다.\n\n## Sources\n\n- [SQLite](https://sqlite.org/fts5.html)\n",
            encoding="utf-8",
        )
        (self.root / "docs" / "decisions" / "index.md").write_text(
            "---\nid: DECISION-INDEX\ntype: decision\n---\n\n# BM25 선택\n\n"
            "정책에 따라 BM25를 선택한다.\n\n- [정책](../policies/security.md)\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_minimal_documents_validate_and_long_body_only_warns(self) -> None:
        report = validate(self.root)
        self.assertTrue(report["valid"], report)
        policy = self.root / "docs" / "policies" / "security.md"
        policy.write_text(policy.read_text(encoding="utf-8") + "\n" + "\n".join("line" for _ in range(60)), encoding="utf-8")
        report = validate(self.root)
        self.assertTrue(report["valid"])
        self.assertTrue(any("consider splitting" in warning for warning in report["warnings"]))

    def test_legacy_frontmatter_is_rejected(self) -> None:
        policy = self.root / "docs" / "policies" / "security.md"
        policy.write_text(policy.read_text(encoding="utf-8").replace("type: policy", "type: policy\nstatus: active"), encoding="utf-8")
        report = validate(self.root)
        self.assertFalse(report["valid"])
        self.assertTrue(any("unsupported frontmatter" in error for error in report["errors"]))

    def test_bm25_auto_rebuild_and_progressive_read(self) -> None:
        result = search(self.root, "로컬 검색")
        self.assertTrue(result["index_rebuilt"])
        self.assertEqual(result["results"][0]["id"], "POLICY-SECURITY")
        again = search(self.root, "로컬 검색")
        self.assertFalse(again["index_rebuilt"])
        document = read(self.root, "DECISION-INDEX")
        self.assertEqual(document["outgoing"], ["POLICY-SECURITY"])
        policy = read(self.root, "POLICY-SECURITY")
        self.assertEqual(policy["backlinks"], ["DECISION-INDEX", "MAP-ROOT"])
        self.assertEqual(policy["sources"][0]["url"], "https://sqlite.org/fts5.html")

    def test_sync_records_create_update_move_delete_once(self) -> None:
        first = sync(self.root)
        self.assertEqual(len(first["history_events"]), 3)
        self.assertEqual(sync(self.root)["history_events"], [])
        source = self.root / "docs" / "decisions" / "index.md"
        moved = self.root / "docs" / "decisions" / "bm25.md"
        source.rename(moved)
        events = sync(self.root)["history_events"]
        self.assertEqual(events[0]["event"], "moved")
        moved.unlink()
        events = sync(self.root)["history_events"]
        self.assertEqual(events[0]["event"], "deleted")
        history = document_history(self.root, "DECISION-INDEX")
        self.assertEqual([event["event"] for event in history], ["created", "moved", "deleted"])

    def test_status_refuses_old_schema(self) -> None:
        config = self.root / ".knowledge" / "config.yml"
        config.write_text("version: 5\n", encoding="utf-8")
        self.assertEqual(status(self.root)["status"], "unsupported_schema")
        with self.assertRaises(TreeWikiError):
            initialize(self.root)


if __name__ == "__main__":
    unittest.main()
