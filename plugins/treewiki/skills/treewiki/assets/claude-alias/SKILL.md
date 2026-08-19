---
name: treewiki
description: Route an explicit /treewiki request to the installed TreeWiki Claude plugin.
disable-model-invocation: true
---

# TreeWiki entrypoint

Pass the current unfinished conversation request and `$ARGUMENTS` unchanged to the
`treewiki:route` plugin skill. Let that skill inspect repository state and select
the operating mode. Do not choose a mode or mutate TreeWiki files in this alias.

Expected TreeWiki plugin version: `{{TREEWIKI_PLUGIN_VERSION}}`.

If `treewiki:route` is unavailable or reports a different version, stop before a
write and tell the user to install or upgrade the TreeWiki Claude plugin. Do not
fall back to an unrelated skill with the same display name.
