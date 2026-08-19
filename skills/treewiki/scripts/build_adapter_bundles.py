from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import importlib.metadata
from pathlib import Path


RELEASE = "0.2.1"
RUNTIME_FILES = (
    "build_embedding_index.py",
    "build_search_index.py",
    "claude_alias.py",
    "document_history.py",
    "knowledge_cli.py",
    "memory_policy.py",
    "okf_v02.py",
    "release_manifest.py",
    "upgrade.py",
    "validate_knowledge.py",
)
CLAUDE_RUNTIME_DIR = Path("plugins/treewiki-claude/runtime")
AGENT_PLUGIN_ROOT = Path("plugins/treewiki")


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def core_hash(files: dict[str, str]) -> str:
    payload = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build(repository: Path, *, check: bool = False) -> dict:
    source = repository / "skills" / "treewiki" / "scripts"
    expected = {name: sha256(source / name) for name in RUNTIME_FILES}
    manifest = {
        "schema": "treewiki.adapter-runtime/v1",
        "release_version": RELEASE,
        "core_version": RELEASE,
        "core_hash": core_hash(expected),
        "files": expected,
    }
    observed_by_adapter: dict[str, dict[str, str]] = {}
    mismatches: list[str] = []
    destinations = {
        "claude": repository / CLAUDE_RUNTIME_DIR,
        "agent_plugin": repository / AGENT_PLUGIN_ROOT / "skills" / "treewiki" / "scripts",
    }
    if not check:
        destination_skill = repository / AGENT_PLUGIN_ROOT / "skills" / "treewiki"
        if destination_skill.exists():
            shutil.rmtree(destination_skill)
        shutil.copytree(
            source.parent,
            destination_skill,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )
        # Codex's plugin validator accepts the standard skill front matter but not
        # TreeWiki's release marker. Version authority remains in both manifests.
        bundled_skill = destination_skill / "SKILL.md"
        bundled_skill.write_text(
            "\n".join(
                line
                for line in bundled_skill.read_text(encoding="utf-8").splitlines()
                if not line.startswith("release:")
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        try:
            distribution = importlib.metadata.distribution("PyYAML")
            yaml_source = Path(distribution.locate_file("yaml"))
            vendor_root = repository / AGENT_PLUGIN_ROOT / "vendor"
            yaml_destination = vendor_root / "yaml"
            if yaml_destination.exists():
                shutil.rmtree(yaml_destination)
            shutil.copytree(
                yaml_source,
                yaml_destination,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyd", "*.so"),
            )
            for vendored_python in yaml_destination.rglob("*.py"):
                source_text = vendored_python.read_text(encoding="utf-8")
                normalized = "\n".join(
                    line.rstrip() for line in source_text.splitlines()
                ).rstrip() + "\n"
                vendored_python.write_text(
                    normalized,
                    encoding="utf-8",
                    newline="\n",
                )
            license_file = next(
                Path(distribution.locate_file(item))
                for item in distribution.files or []
                if str(item).lower().endswith("license")
            )
            shutil.copy2(license_file, vendor_root / "PyYAML-LICENSE")
        except (importlib.metadata.PackageNotFoundError, OSError, StopIteration) as exc:
            raise RuntimeError("PyYAML is required to build the portable vendor runtime") from exc

    for adapter, destination in destinations.items():
        if not check:
            destination.mkdir(parents=True, exist_ok=True)
            if adapter == "claude":
                for name in RUNTIME_FILES:
                    shutil.copy2(source / name, destination / name)
            manifest_destination = (
                destination / "runtime-manifest.json"
                if adapter == "claude"
                else repository / AGENT_PLUGIN_ROOT / "runtime-manifest.json"
            )
            manifest_destination.write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        observed = {
            name: sha256(destination / name) if (destination / name).is_file() else "missing"
            for name in RUNTIME_FILES
        }
        observed_by_adapter[adapter] = observed
        mismatches.extend(
            f"{adapter}:{name}"
            for name in RUNTIME_FILES
            if expected[name] != observed[name]
        )
    vendor_yaml = repository / AGENT_PLUGIN_ROOT / "vendor" / "yaml" / "__init__.py"
    vendor_license = repository / AGENT_PLUGIN_ROOT / "vendor" / "PyYAML-LICENSE"
    if not vendor_yaml.is_file() or not vendor_license.is_file():
        mismatches.append("agent_plugin:vendored-pyyaml")
    return {
        "expected": expected,
        "observed": observed_by_adapter["claude"],
        "adapters": observed_by_adapter,
        "mismatches": sorted(mismatches),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", nargs="?", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = build(Path(args.repository).resolve(), check=args.check)
    if result["mismatches"]:
        print("MISMATCH " + ",".join(result["mismatches"]))
        return 1
    print("VALID treewiki adapter runtime")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
