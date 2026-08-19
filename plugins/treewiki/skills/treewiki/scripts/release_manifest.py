from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

import yaml


SUPPORTED_MANIFEST_FORMAT = 1
MANIFEST_FILENAME = "treewiki-release.yml"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class ManifestErrorCode(str, Enum):
    INVALID = "SOURCE_INVALID"
    INCOMPATIBLE_NEWER = "INCOMPATIBLE_NEWER"
    IO_FAILURE = "IO_FAILURE"
    PATH_TRAVERSAL = "PATH_TRAVERSAL"
    HASH_MISMATCH = "HASH_MISMATCH"
    ARTIFACT_MISSING = "ARTIFACT_MISSING"
    ARTIFACT_LIST_INCOMPLETE = "ARTIFACT_LIST_INCOMPLETE"


class ManifestValidationError(ValueError):
    def __init__(
        self,
        code: ManifestErrorCode,
        message: str,
        *,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: str) -> "SemVer":
        if not isinstance(value, str):
            raise ManifestValidationError(
                ManifestErrorCode.INVALID, "SemVer value must be a string"
            )
        match = SEMVER_RE.fullmatch(value)
        if not match:
            raise ManifestValidationError(
                ManifestErrorCode.INVALID, f"invalid SemVer: {value!r}"
            )
        prerelease = tuple(match.group(4).split(".")) if match.group(4) else ()
        build = tuple(match.group(5).split(".")) if match.group(5) else ()
        return cls(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            prerelease,
            build,
        )

    def __str__(self) -> str:
        value = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            value += "-" + ".".join(self.prerelease)
        if self.build:
            value += "+" + ".".join(self.build)
        return value

    def _precedence(self) -> tuple[int, int, int]:
        return self.major, self.minor, self.patch

    @staticmethod
    def _compare_identifiers(left: tuple[str, ...], right: tuple[str, ...]) -> int:
        if not left and not right:
            return 0
        if not left:
            return 1
        if not right:
            return -1
        for lhs, rhs in zip(left, right):
            if lhs == rhs:
                continue
            lhs_numeric = lhs.isdigit()
            rhs_numeric = rhs.isdigit()
            if lhs_numeric and rhs_numeric:
                return -1 if int(lhs) < int(rhs) else 1
            if lhs_numeric != rhs_numeric:
                return -1 if lhs_numeric else 1
            return -1 if lhs < rhs else 1
        return (len(left) > len(right)) - (len(left) < len(right))

    def compare(self, other: "SemVer") -> int:
        if not isinstance(other, SemVer):
            return NotImplemented
        if self._precedence() != other._precedence():
            return -1 if self._precedence() < other._precedence() else 1
        return self._compare_identifiers(self.prerelease, other.prerelease)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self.compare(other) < 0

    def __le__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self.compare(other) <= 0

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self.compare(other) > 0

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self.compare(other) >= 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return False
        return self.compare(other) == 0

    def __hash__(self) -> int:
        # SemVer build metadata does not affect precedence or equality.
        return hash((self.major, self.minor, self.patch, self.prerelease))


def compare_semver(left: str | SemVer, right: str | SemVer) -> int:
    lhs = left if isinstance(left, SemVer) else SemVer.parse(left)
    rhs = right if isinstance(right, SemVer) else SemVer.parse(right)
    return lhs.compare(rhs)


@dataclass(frozen=True)
class ConfigSchema:
    minimum: int
    current: int
    maximum: int


@dataclass(frozen=True)
class Compatibility:
    legacy_skill: str
    mode: str
    introduced_in: SemVer
    remove_in: SemVer


@dataclass(frozen=True)
class Distribution:
    installer: str
    repository: str
    canonical_skill: str
    install_command: str


@dataclass(frozen=True)
class Artifact:
    path: str
    sha256: str


@dataclass(frozen=True)
class ReleaseManifest:
    format: int
    product: str
    display_name: str
    release: SemVer
    repository: str
    source_ref: str
    config_schema: ConfigSchema
    compatibility: Compatibility
    distribution: Distribution
    artifacts: tuple[Artifact, ...]
    raw: Mapping[str, Any] = field(repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        # Round-tripping the raw mapping intentionally preserves unknown fields.
        return _plain_data(self.raw)


@dataclass(frozen=True)
class ArtifactProblem:
    code: ManifestErrorCode
    path: str
    message: str
    expected: str | None = None
    observed: str | None = None


def _plain_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_data(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestValidationError(
            ManifestErrorCode.INVALID, f"{name} must be a mapping"
        )
    return value


def _required_string(mapping: Mapping[str, Any], key: str, prefix: str = "") -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError(
            ManifestErrorCode.INVALID, f"{prefix}{key} must be a non-empty string"
        )
    return value


def _required_int(mapping: Mapping[str, Any], key: str, prefix: str = "") -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ManifestValidationError(
            ManifestErrorCode.INVALID, f"{prefix}{key} must be an integer"
        )
    return value


def validate_artifact_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ManifestValidationError(
            ManifestErrorCode.PATH_TRAVERSAL, "artifact path must be a non-empty string"
        )
    if "\\" in value:
        raise ManifestValidationError(
            ManifestErrorCode.PATH_TRAVERSAL,
            f"artifact path must use POSIX separators: {value!r}",
            path=value,
        )
    path = PurePosixPath(value)
    if path.is_absolute() or value.startswith("/") or ":" in value:
        raise ManifestValidationError(
            ManifestErrorCode.PATH_TRAVERSAL,
            f"artifact path must be relative: {value!r}",
            path=value,
        )
    if value != path.as_posix() or any(part in {"", ".", ".."} for part in path.parts):
        raise ManifestValidationError(
            ManifestErrorCode.PATH_TRAVERSAL,
            f"artifact path is not canonical: {value!r}",
            path=value,
        )
    if path.name == MANIFEST_FILENAME or "__pycache__" in path.parts or path.suffix == ".pyc":
        raise ManifestValidationError(
            ManifestErrorCode.INVALID,
            f"artifact path is excluded from the manifest: {value!r}",
            path=value,
        )
    return path.as_posix()


def resolve_artifact_path(skill_root: Path, artifact_path: str) -> Path:
    canonical = validate_artifact_path(artifact_path)
    root = Path(skill_root).resolve(strict=True)
    candidate = (root / Path(*PurePosixPath(canonical).parts)).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ManifestValidationError(
            ManifestErrorCode.PATH_TRAVERSAL,
            f"artifact escapes skill root: {artifact_path!r}",
            path=artifact_path,
        ) from exc
    return candidate


def parse_manifest(data: Mapping[str, Any]) -> ReleaseManifest:
    root = _mapping(data, "manifest")
    format_version = _required_int(root, "format")
    if format_version > SUPPORTED_MANIFEST_FORMAT:
        raise ManifestValidationError(
            ManifestErrorCode.INCOMPATIBLE_NEWER,
            f"manifest format {format_version} is newer than supported format "
            f"{SUPPORTED_MANIFEST_FORMAT}",
        )
    if format_version != SUPPORTED_MANIFEST_FORMAT:
        raise ManifestValidationError(
            ManifestErrorCode.INVALID,
            f"manifest format must be {SUPPORTED_MANIFEST_FORMAT}",
        )

    release = SemVer.parse(_required_string(root, "release"))
    source_ref = _required_string(root, "source_ref")
    if source_ref != f"v{release}":
        raise ManifestValidationError(
            ManifestErrorCode.INVALID,
            f"source_ref {source_ref!r} must match release tag v{release}",
        )

    schema_raw = _mapping(root.get("config_schema"), "config_schema")
    schema = ConfigSchema(
        _required_int(schema_raw, "minimum", "config_schema."),
        _required_int(schema_raw, "current", "config_schema."),
        _required_int(schema_raw, "maximum", "config_schema."),
    )
    if schema.minimum < 1 or not schema.minimum <= schema.current <= schema.maximum:
        raise ManifestValidationError(
            ManifestErrorCode.INVALID,
            "config_schema must satisfy 1 <= minimum <= current <= maximum",
        )

    compatibility_raw = _mapping(root.get("compatibility"), "compatibility")
    compatibility = Compatibility(
        legacy_skill=_required_string(compatibility_raw, "legacy_skill", "compatibility."),
        mode=_required_string(compatibility_raw, "mode", "compatibility."),
        introduced_in=SemVer.parse(
            _required_string(compatibility_raw, "introduced_in", "compatibility.")
        ),
        remove_in=SemVer.parse(
            _required_string(compatibility_raw, "remove_in", "compatibility.")
        ),
    )
    removed_mode = compatibility.mode == "removed"
    invalid_compatibility = (
        compatibility.introduced_in > release
        or compatibility.remove_in <= compatibility.introduced_in
        or (not removed_mode and compatibility.remove_in <= release)
        or (removed_mode and compatibility.remove_in > release)
    )
    if invalid_compatibility:
        raise ManifestValidationError(
            ManifestErrorCode.INVALID,
            "compatibility versions do not match the declared compatibility mode",
        )

    distribution_raw = _mapping(root.get("distribution"), "distribution")
    distribution = Distribution(
        installer=_required_string(distribution_raw, "installer", "distribution."),
        repository=_required_string(distribution_raw, "repository", "distribution."),
        canonical_skill=_required_string(
            distribution_raw, "canonical_skill", "distribution."
        ),
        install_command=_required_string(
            distribution_raw, "install_command", "distribution."
        ),
    )
    repository = _required_string(root, "repository")
    if distribution.repository != repository:
        raise ManifestValidationError(
            ManifestErrorCode.INVALID,
            "distribution.repository must equal repository",
        )

    artifacts_raw = _mapping(root.get("artifacts"), "artifacts").get("files")
    if not isinstance(artifacts_raw, list) or not artifacts_raw:
        raise ManifestValidationError(
            ManifestErrorCode.INVALID, "artifacts.files must be a non-empty list"
        )
    artifacts: list[Artifact] = []
    seen: set[str] = set()
    for index, item in enumerate(artifacts_raw):
        artifact_raw = _mapping(item, f"artifacts.files[{index}]")
        path = validate_artifact_path(
            _required_string(artifact_raw, "path", f"artifacts.files[{index}].")
        )
        digest = _required_string(
            artifact_raw, "sha256", f"artifacts.files[{index}]."
        )
        if not SHA256_RE.fullmatch(digest):
            raise ManifestValidationError(
                ManifestErrorCode.INVALID,
                f"artifacts.files[{index}].sha256 must be 64 lowercase hex characters",
                path=path,
            )
        if path in seen:
            raise ManifestValidationError(
                ManifestErrorCode.INVALID, f"duplicate artifact path: {path}", path=path
            )
        seen.add(path)
        artifacts.append(Artifact(path, digest))
    if [artifact.path for artifact in artifacts] != sorted(seen):
        raise ManifestValidationError(
            ManifestErrorCode.INVALID,
            "artifacts.files must be sorted by path for deterministic releases",
        )

    return ReleaseManifest(
        format=format_version,
        product=_required_string(root, "product"),
        display_name=_required_string(root, "display_name"),
        release=release,
        repository=repository,
        source_ref=source_ref,
        config_schema=schema,
        compatibility=compatibility,
        distribution=distribution,
        artifacts=tuple(artifacts),
        raw=_plain_data(root),
    )


def load_manifest(path: str | Path) -> ReleaseManifest:
    manifest_path = Path(path)
    try:
        if not manifest_path.is_file():
            raise ManifestValidationError(
                ManifestErrorCode.IO_FAILURE,
                f"manifest is not a regular file: {manifest_path}",
                path=str(manifest_path),
            )
        loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except ManifestValidationError:
        raise
    except yaml.YAMLError as exc:
        raise ManifestValidationError(
            ManifestErrorCode.INVALID,
            f"cannot parse manifest {manifest_path}: {exc}",
            path=str(manifest_path),
        ) from exc
    except (OSError, UnicodeError) as exc:
        raise ManifestValidationError(
            ManifestErrorCode.IO_FAILURE,
            f"cannot read manifest {manifest_path}: {exc}",
            path=str(manifest_path),
        ) from exc
    return parse_manifest(_mapping(loaded, "manifest"))


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        _plain_data(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def manifest_digest(manifest: ReleaseManifest | Mapping[str, Any]) -> str:
    value = manifest.to_dict() if isinstance(manifest, ReleaseManifest) else value_or_mapping(manifest)
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def value_or_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_distribution_files(skill_root: Path) -> Iterable[Path]:
    root = Path(skill_root).resolve(strict=True)
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        if path.is_symlink():
            raise ManifestValidationError(
                ManifestErrorCode.PATH_TRAVERSAL,
                f"distribution artifact must be a regular file, not a symlink: {path}",
                path=path.relative_to(root).as_posix(),
            )
        relative = path.relative_to(root)
        if (
            relative.name == MANIFEST_FILENAME
            or "__pycache__" in relative.parts
            or relative.suffix == ".pyc"
        ):
            continue
        yield path


def verify_payload(
    manifest: ReleaseManifest,
    skill_root: str | Path,
    *,
    require_complete: bool = True,
) -> list[ArtifactProblem]:
    root = Path(skill_root)
    problems: list[ArtifactProblem] = []
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        return [
            ArtifactProblem(
                ManifestErrorCode.IO_FAILURE,
                "",
                f"cannot resolve skill payload root: {exc}",
            )
        ]
    if not resolved_root.is_dir():
        return [
            ArtifactProblem(
                ManifestErrorCode.IO_FAILURE,
                "",
                f"skill payload root is not a directory: {resolved_root}",
            )
        ]
    expected_paths = {artifact.path for artifact in manifest.artifacts}
    for artifact in manifest.artifacts:
        try:
            path = resolve_artifact_path(resolved_root, artifact.path)
        except (OSError, ManifestValidationError) as exc:
            if isinstance(exc, ManifestValidationError):
                code = exc.code
            else:
                code = ManifestErrorCode.IO_FAILURE
            problems.append(ArtifactProblem(code, artifact.path, str(exc)))
            continue
        if not path.is_file():
            problems.append(
                ArtifactProblem(
                    ManifestErrorCode.ARTIFACT_MISSING,
                    artifact.path,
                    f"artifact is missing: {artifact.path}",
                    expected=artifact.sha256,
                )
            )
            continue
        try:
            observed = sha256_file(path)
        except OSError as exc:
            problems.append(
                ArtifactProblem(
                    ManifestErrorCode.IO_FAILURE,
                    artifact.path,
                    f"cannot hash artifact {artifact.path}: {exc}",
                    expected=artifact.sha256,
                )
            )
            continue
        if observed != artifact.sha256:
            problems.append(
                ArtifactProblem(
                    ManifestErrorCode.HASH_MISMATCH,
                    artifact.path,
                    f"artifact hash mismatch: {artifact.path}",
                    expected=artifact.sha256,
                    observed=observed,
                )
            )
    if require_complete:
        try:
            observed_paths = {
                path.relative_to(resolved_root).as_posix()
                for path in iter_distribution_files(resolved_root)
            }
        except (OSError, ManifestValidationError) as exc:
            code = (
                exc.code
                if isinstance(exc, ManifestValidationError)
                else ManifestErrorCode.IO_FAILURE
            )
            problems.append(
                ArtifactProblem(
                    code, "", f"cannot enumerate skill payload: {exc}"
                )
            )
        else:
            for extra in sorted(observed_paths - expected_paths):
                problems.append(
                    ArtifactProblem(
                        ManifestErrorCode.ARTIFACT_LIST_INCOMPLETE,
                        extra,
                        f"artifact is not listed in manifest: {extra}",
                    )
                )
    return problems


def validate_manifest_file(
    manifest_path: str | Path, *, require_complete: bool = True
) -> ReleaseManifest:
    path = Path(manifest_path).resolve(strict=True)
    manifest = load_manifest(path)
    problems = verify_payload(manifest, path.parent, require_complete=require_complete)
    if problems:
        first = problems[0]
        raise ManifestValidationError(first.code, first.message, path=first.path)
    return manifest


# Small compatibility aliases keep the knowledge_cli integration unsurprising.
validate_manifest = parse_manifest
verify_artifacts = verify_payload
