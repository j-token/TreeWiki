# TreeWiki starter schema

```text
AGENTS.md
docs/
  vocabulary/
    glossary.yml
    topics.yml
  memory/
    l1/
    l2/
    l3/
.knowledge/
  config.yml
  private-memory/
    l0/
  index/
```

Only `.knowledge/private-memory/l0/` is local and Git-ignored. Approved shared memory belongs in `docs/memory/l1/`, `l2/`, and `l3/`; it must hold opaque provenance metadata instead of raw source text. `.knowledge/index/` is derived and recreatable.

New distributions use `treewiki/skills/treewiki/`. A compatibility shim may recognize the prior installation name through 0.1.x; remove it in 0.2.0 only after installation and regression checks succeed.
