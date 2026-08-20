from __future__ import annotations

import json
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "treewiki"
FIXTURES = ROOT / "tests" / "fixtures" / "agent-plugins"


class AgentPluginManifestTests(unittest.TestCase):
    def load(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def test_portable_manifests_match_offline_official_schemas(self) -> None:
        jsonschema.Draft202012Validator(self.load(FIXTURES / "plugin.schema.json")).validate(
            self.load(PLUGIN / "plugin.json")
        )
        jsonschema.Draft202012Validator(self.load(FIXTURES / "mcp.schema.json")).validate(
            self.load(PLUGIN / "mcp.json")
        )

    def test_unknown_fields_and_schema_version_are_rejected(self) -> None:
        schema = self.load(FIXTURES / "plugin.schema.json")
        validator = jsonschema.Draft202012Validator(schema)
        manifest = self.load(PLUGIN / "plugin.json")
        self.assertTrue(list(validator.iter_errors({**manifest, "codex": {}})))
        self.assertTrue(list(validator.iter_errors({**manifest, "$schema": manifest["$schema"].replace("1.0.0", "2.0.0")})))

    def test_mcp_paths_are_contained_and_reserved_env_is_rejected(self) -> None:
        schema = self.load(FIXTURES / "mcp.schema.json")
        validator = jsonschema.Draft202012Validator(schema)
        mcp = self.load(PLUGIN / "mcp.json")
        server = mcp["mcpServers"]["treewiki"]
        self.assertEqual(server["cwd"], "${PLUGIN_ROOT}")
        self.assertTrue(server["args"][0].startswith("${PLUGIN_ROOT}/"))
        escaped = {**mcp, "mcpServers": {"treewiki": {**server, "cwd": "../outside"}}}
        reserved = {**mcp, "mcpServers": {"treewiki": {**server, "env": {"PLUGIN_DATA": "bad"}}}}
        self.assertTrue(list(validator.iter_errors(escaped)))
        self.assertTrue(list(validator.iter_errors(reserved)))

    def test_codex_mcp_bridge_matches_portable_server(self) -> None:
        portable = self.load(PLUGIN / "mcp.json")
        codex = self.load(PLUGIN / ".mcp.json")
        self.assertEqual(codex["mcpServers"], portable["mcpServers"])
        manifest = self.load(PLUGIN / ".codex-plugin" / "plugin.json")
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        self.assertEqual(manifest["version"], "0.2.1")
        self.assertEqual(manifest["interface"]["displayName"], "TreeWiki")
        self.assertEqual(
            manifest["interface"]["capabilities"],
            ["Skills", "Native MCP tools", "Governed memory"],
        )


if __name__ == "__main__":
    unittest.main()
