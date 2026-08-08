# Lifecycle and relations

Documents move `draft -> active -> deprecated -> archived`; use `supersedes` rather than deletion. Active contracts require `verified_by`. Relations include `derived_from`, `depends_on`, `supersedes`, `verified_by`, `implemented_by`, and `related_to`.

For shared memory, preserve IDs and opaque provenance across migration. L3 candidates begin `proposed`; approval records the actor before activation. A name transition never rewrites historical identifiers or provenance URLs.
