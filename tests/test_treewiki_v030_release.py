from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "treewiki"
CLAUDE = ROOT / "plugins" / "treewiki-claude"


class TreeWikiV030ReleaseTests(unittest.TestCase):
    def test_all_plugin_versions_are_030(self) -> None:
        files = [
            PLUGIN / "plugin.json",
            PLUGIN / ".codex-plugin" / "plugin.json",
            PLUGIN / "package.json",
            CLAUDE / ".claude-plugin" / "plugin.json",
        ]
        for path in files:
            with self.subTest(path=path):
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], "0.3.0")
        marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(marketplace["plugins"][0]["version"], "0.3.0")

    def test_plugin_is_the_only_canonical_skill_source(self) -> None:
        self.assertFalse((ROOT / "skills" / "treewiki").exists())
        self.assertTrue((PLUGIN / "skills" / "treewiki" / "SKILL.md").is_file())
        skill = (PLUGIN / "skills" / "treewiki" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("no document ACL", skill)
        self.assertNotIn("L3_CANDIDATE", skill)

    def test_claude_runtime_matches_canonical_python_core(self) -> None:
        manifest = json.loads((CLAUDE / "runtime" / "runtime-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["release_version"], "0.3.0")
        for name, expected in manifest["files"].items():
            source = PLUGIN / "skills" / "treewiki" / "scripts" / name
            generated = CLAUDE / "runtime" / name
            self.assertEqual(source.read_bytes(), generated.read_bytes())
            actual = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(actual, expected)
        self.assertEqual(
            (PLUGIN / "skills" / "treewiki" / "assets" / "claude-route.md").read_bytes(),
            (CLAUDE / "skills" / "route" / "SKILL.md").read_bytes(),
        )

    def test_release_manifest_hashes_every_declared_artifact(self) -> None:
        manifest = json.loads((PLUGIN / "release-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "0.3.0")
        for relative, expected in manifest["files"].items():
            path = ROOT / relative
            self.assertTrue(path.is_file(), relative)
            actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(actual, expected, relative)

    def test_managed_templates_use_only_id_and_type(self) -> None:
        for name in ("AGENTS.md", "policy.md", "decision.md"):
            text = (PLUGIN / "skills" / "treewiki" / "assets" / name).read_text(encoding="utf-8")
            frontmatter = text.split("---", 2)[1]
            keys = [line.split(":", 1)[0].strip() for line in frontmatter.splitlines() if ":" in line]
            self.assertEqual(keys, ["id", "type"])


if __name__ == "__main__":
    unittest.main()
