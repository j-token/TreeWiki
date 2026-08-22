# TreeWiki Claude Plugin

This package exposes `/treewiki` for project policy and decision work. Its skill, Python runtime, and YAML dependency are generated from the canonical [Agent Plugin](../treewiki/README.md).

Do not edit `runtime/`, `vendor/`, or `skills/route/` directly. Rebuild them from the repository root with:

```powershell
Push-Location plugins/treewiki
npm run build:claude
Pop-Location
```
