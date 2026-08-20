"""Deterministic body budgets for atomic managed Markdown documents."""

from __future__ import annotations

from typing import Any, Mapping


DEFAULT_BODY_LINE_TARGET = 50
DEFAULT_BODY_LINE_HARD_LIMIT = 80
DEFAULT_BODY_TOKEN_HARD_LIMIT = 1000


def _positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def composition_limits(
    documents: Mapping[str, Any] | None,
) -> tuple[dict[str, int], list[str]]:
    """Return normalized limits and configuration errors."""

    defaults = {
        "body_line_target": DEFAULT_BODY_LINE_TARGET,
        "body_line_hard_limit": DEFAULT_BODY_LINE_HARD_LIMIT,
        "body_token_hard_limit": DEFAULT_BODY_TOKEN_HARD_LIMIT,
    }
    raw = documents.get("composition", {}) if isinstance(documents, Mapping) else {}
    if not isinstance(raw, Mapping):
        return defaults, ["documents.composition must be a mapping"]

    limits = dict(defaults)
    errors: list[str] = []
    for key, default in defaults.items():
        value = raw.get(key, default)
        if not _positive_integer(value):
            errors.append(f"documents.composition.{key} must be a positive integer")
            continue
        limits[key] = value
    if limits["body_line_hard_limit"] < limits["body_line_target"]:
        errors.append(
            "documents.composition.body_line_hard_limit must be greater than or equal to body_line_target"
        )
    return limits, errors


def body_metrics(body: str) -> tuple[int, int]:
    """Count physical body lines and estimate tokens using the indexer's 4-char rule."""

    normalized = body.strip("\r\n")
    if not normalized:
        return 0, 0
    return len(normalized.splitlines()), (len(normalized) + 3) // 4


def document_composition_messages(
    metadata: Mapping[str, Any],
    body: str,
    *,
    limits: Mapping[str, int],
) -> tuple[list[str], list[str]]:
    """Return hard-limit errors and target-limit warnings for one document."""

    errors: list[str] = []
    warnings: list[str] = []
    composition = metadata.get("composition")
    exception: str | None = None
    if composition is not None:
        if not isinstance(composition, Mapping):
            errors.append("composition must be a mapping")
        else:
            raw_exception = composition.get("size_exception")
            if raw_exception is not None:
                if not isinstance(raw_exception, str) or not raw_exception.strip():
                    errors.append("composition.size_exception must be a non-empty reason")
                else:
                    exception = raw_exception.strip()

    lines, estimated_tokens = body_metrics(body)
    if exception:
        return errors, warnings

    line_target = limits["body_line_target"]
    line_hard_limit = limits["body_line_hard_limit"]
    token_hard_limit = limits["body_token_hard_limit"]
    if lines > line_hard_limit or estimated_tokens > token_hard_limit:
        errors.append(
            f"body exceeds composition hard limit ({lines} lines, about {estimated_tokens} tokens); "
            "split independent topics into a directory with an AGENTS.md map or declare "
            "composition.size_exception"
        )
    elif lines > line_target:
        warnings.append(
            f"body has {lines} lines (target {line_target}); split independent H2 sections "
            "into a directory with an AGENTS.md map"
        )
    return errors, warnings
