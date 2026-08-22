from __future__ import annotations

import json
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "treewiki"
FIXTURES = ROOT / "tests" / "fixtures" / "agent-plugins"


class AgentPluginManifestTests(unittest.TestCase):
    @staticmethod
    def load(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def test_portable_manifests_match_offline_official_schemas(self) -> None:
        jsonschema.Draft202012Validator(self.load(FIXTURES / "plugin.schema.json")).validate(self.load(PLUGIN / "plugin.json"))
        jsonschema.Draft202012Validator(self.load(FIXTURES / "mcp.schema.json")).validate(self.load(PLUGIN / "mcp.json"))

    def test_codex_bridge_matches_portable_server_and_030_interface(self) -> None:
        portable = self.load(PLUGIN / "mcp.json")
        codex = self.load(PLUGIN / ".mcp.json")
        self.assertEqual(codex["mcpServers"], portable["mcpServers"])
        manifest = self.load(PLUGIN / ".codex-plugin" / "plugin.json")
        self.assertEqual(manifest["version"], "0.3.0")
        self.assertEqual(manifest["interface"]["capabilities"], ["Skills", "Native MCP tools", "Local BM25"])


if __name__ == "__main__":
    unittest.main()
