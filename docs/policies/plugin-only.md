---
id: POLICY-PLUGIN-ONLY-001
type: policy
---

# Maintain TreeWiki only as plugins

TreeWiki is developed and distributed only as the canonical Agent Plugin and its generated Claude Code plugin. The skill and internal CLI are plugin components, not standalone products.

Edit the Agent Plugin first. Generate the Claude skill and runtime from that source, and do not maintain an independent root skill copy.

## Sources

- [Repository map](../../AGENTS.md)
- [Agent Plugin](../../plugins/treewiki/README.md)
