from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml

from build_adapter_bundles import RUNTIME_FILES, core_hash

try:
    from release_manifest import (
        MANIFEST_FILENAME,
        ManifestErrorCode,
        ManifestValidationError,
        iter_distribution_files,
        load_manifest,
        parse_manifest,
        sha256_file,
        verify_payload,
    )
except ImportError:  # pragma: no cover - package-style import
    from .release_manifest import (
        MANIFEST_FILENAME,
        ManifestErrorCode,
        ManifestValidationError,
        iter_distribution_files,
        load_manifest,
        parse_manifest,
        sha256_file,
        verify_payload,
    )


DEFAULT_RELEASE = "0.2.0"
DEFAULT_REPOSITORY = "j-token/treewiki"
DEFAULT_INSTALL_COMMAND = (
    "npx skills add j-token/treewiki --skill treewiki -g -a codex -y --copy"
)


def artifact_entries(skill_root: str | Path) -> list[dict[str, str]]:
    root = Path(skill_root).resolve(strict=True)
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in iter_distribution_files(root)
    ]


def build_manifest_data(
    skill_root: str | Path,
    *,
    release: str = DEFAULT_RELEASE,
    repository: str = DEFAULT_REPOSITORY,
    source_ref: str | None = None,
    base: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    repository_root = Path(skill_root).resolve().parents[1]
    agent_bundle = repository_root / "plugins" / "treewiki" / "dist" / "treewiki-mcp.mjs"
    workbench_bundle = repository_root / "plugins" / "treewiki" / "web" / "dist" / "workbench.html"
    payload: dict[str, Any] = dict(base or {})
    payload.update(
        {
            "format": 1,
            "product": "treewiki",
            "display_name": "TreeWiki",
            "release": release,
            "repository": repository,
            "source_ref": source_ref or f"v{release}",
        }
    )
    payload["config_schema"] = {"minimum": 1, "current": 4, "maximum": 4}
    payload["compatibility"] = {
        "legacy_skill": "lmwiki",
        "mode": "removed" if release == "0.2.0" else "warning-shim",
        "introduced_in": "0.1.0",
        "remove_in": "0.2.0",
    }
    payload["runtime"] = {
        "core_version": release,
        "core_hash": core_hash(
            {
                name: "sha256:" + sha256_file(skill_root / "scripts" / name)
                for name in RUNTIME_FILES
                if (skill_root / "scripts" / name).is_file()
            }
        ),
        "config_version": 4,
        "memory_layout_version": 2,
        "history_schema": 1,
    }
    payload["adapters"] = {
        "codex": {
            "kind": "agent-plugin",
            "entrypoint": "open_treewiki_workbench",
            "specification": "agent-plugins/1.0.0-working-draft",
            "marketplace": "treewiki-marketplace",
            "mcp_transport": "stdio",
            "runtime_bundle": "plugins/treewiki/dist/treewiki-mcp.mjs",
            "ui_resource": "ui://treewiki/workbench-v1.html",
            "bundle_hash": (
                "sha256:" + sha256_file(agent_bundle) if agent_bundle.is_file() else "missing"
            ),
            "workbench_hash": (
                "sha256:" + sha256_file(workbench_bundle)
                if workbench_bundle.is_file()
                else "missing"
            ),
        },
        "claude": {
            "kind": "plugin",
            "entrypoint": "/treewiki",
            "runtime_bundle": "plugins/treewiki-claude/runtime",
        },
    }
    payload.setdefault(
        "distribution",
        {
            "installer": "skills-cli",
            "repository": repository,
            "canonical_skill": "treewiki",
            "install_command": DEFAULT_INSTALL_COMMAND,
        },
    )
    # Repository is not an unknown extension: it must follow an explicit override.
    distribution = dict(payload["distribution"])
    distribution["repository"] = repository
    payload["distribution"] = distribution
    payload["artifacts"] = {"files": artifact_entries(skill_root)}
    parse_manifest(payload)
    return payload


def write_release_manifest(
    skill_root: str | Path,
    output: str | Path | None = None,
    *,
    release: str = DEFAULT_RELEASE,
    repository: str = DEFAULT_REPOSITORY,
    source_ref: str | None = None,
    preserve_unknown: bool = True,
) -> Path:
    root = Path(skill_root).resolve(strict=True)
    destination = Path(output).resolve() if output else root / MANIFEST_FILENAME
    base: Mapping[str, Any] | None = None
    if preserve_unknown and destination.is_file():
        loaded = yaml.safe_load(destination.read_text(encoding="utf-8"))
        if isinstance(loaded, Mapping):
            base = loaded
    data = build_manifest_data(
        root,
        release=release,
        repository=repository,
        source_ref=source_ref,
        base=base,
    )
    manifest = parse_manifest(data)
    problems = verify_payload(manifest, root, require_complete=True)
    if problems:
        raise ManifestValidationError(
            problems[0].code, problems[0].message, path=problems[0].path
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        # Re-parse the exact staged bytes before replacing an existing authority file.
        staged = load_manifest(temporary)
        if staged.to_dict() != manifest.to_dict():
            raise ManifestValidationError(
                code=ManifestErrorCode.INVALID,
                message="staged manifest changed during serialization",
                path=temporary.as_posix(),
            )
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def check_release_manifest(path: str | Path) -> list[str]:
    manifest_path = Path(path).resolve(strict=True)
    manifest = load_manifest(manifest_path)
    return [
        problem.message
        for problem in verify_payload(
            manifest, manifest_path.parent, require_complete=True
        )
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or verify a deterministic TreeWiki release manifest."
    )
    parser.add_argument(
        "skill_root",
        nargs="?",
        default=str(Path(__file__).resolve().parents[1]),
    )
    parser.add_argument("--output")
    parser.add_argument("--release", default=DEFAULT_RELEASE)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--source-ref")
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = Path(args.skill_root).resolve(strict=True)
        destination = Path(args.output).resolve() if args.output else root / MANIFEST_FILENAME
        if args.check:
            problems = check_release_manifest(destination)
            if problems:
                for problem in problems:
                    print(f"ERROR {problem}", file=sys.stderr)
                return 1
            print(f"VALID {destination}")
            return 0
        result = write_release_manifest(
            root,
            destination,
            release=args.release,
            repository=args.repository,
            source_ref=args.source_ref,
        )
    except (OSError, UnicodeError, yaml.YAMLError, ManifestValidationError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    print(f"WROTE {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
