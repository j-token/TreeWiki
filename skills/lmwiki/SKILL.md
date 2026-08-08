---
name: lmwiki
description: Deprecated TreeWiki 0.1 compatibility shim. Redirects legacy $lmwiki calls to $treewiki without owning an implementation.
---

# LMWiki compatibility shim

`$lmwiki` is the former name of `$treewiki`. This warning shim exists only for TreeWiki 0.1.x and is removed in 0.2.0.

Use the sibling canonical skill at `../treewiki/SKILL.md`. Do not create, migrate, or delete repository data from this shim. If the canonical skill is absent, install it and rerun the original request:

```powershell
npx skills add j-token/treewiki --skill treewiki -g -a codex -y --copy
```
