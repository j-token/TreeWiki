"""Technical-writing document types, templates, and deterministic quality checks."""

from __future__ import annotations

import re
from typing import Any, Mapping


TECHNICAL_DOCUMENT_TYPES = {
    "how_to",
    "reference",
    "explanation",
    "tutorial",
    "troubleshooting",
    "api_contract",
}

REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "how_to": ("Purpose", "Audience", "Prerequisites", "Procedure", "Success criteria", "Troubleshooting", "Sources"),
    "reference": ("Purpose", "Audience", "Inputs and outputs", "Constraints", "Examples", "Sources"),
    "explanation": ("Purpose", "Audience", "Background", "Core concepts", "Alternatives and tradeoffs", "Sources"),
    "tutorial": ("Purpose", "Audience", "Prerequisites", "Steps", "Success criteria", "Next steps", "Sources"),
    "troubleshooting": ("Purpose", "Audience", "Symptoms", "Causes", "Resolution", "Verification", "Recovery", "Sources"),
    "api_contract": ("Purpose", "Audience", "Inputs", "Outputs", "Errors", "Compatibility", "Examples", "Sources"),
}

SECTION_ALIASES = {
    "purpose": {"purpose", "목적"},
    "audience": {"audience", "대상 독자", "독자"},
    "prerequisites": {"prerequisites", "사전 조건", "전제 조건"},
    "procedure": {"procedure", "절차"},
    "success criteria": {"success criteria", "성공 판정", "완료 조건"},
    "troubleshooting": {"troubleshooting", "문제 해결"},
    "sources": {"sources", "출처", "근거"},
    "inputs and outputs": {"inputs and outputs", "입력과 출력"},
    "constraints": {"constraints", "제약", "제약 사항"},
    "examples": {"examples", "예시"},
    "background": {"background", "배경"},
    "core concepts": {"core concepts", "핵심 내용", "핵심 개념"},
    "alternatives and tradeoffs": {"alternatives and tradeoffs", "대안과 트레이드오프", "대안"},
    "steps": {"steps", "단계"},
    "next steps": {"next steps", "다음 단계"},
    "symptoms": {"symptoms", "증상"},
    "causes": {"causes", "원인"},
    "resolution": {"resolution", "해결 절차", "해결"},
    "verification": {"verification", "검증"},
    "recovery": {"recovery", "복구"},
    "inputs": {"inputs", "입력"},
    "outputs": {"outputs", "출력"},
    "errors": {"errors", "오류", "실패 동작"},
    "compatibility": {"compatibility", "호환성"},
}

HEADING_RE = re.compile(r"^#{2,4}\s+(.+?)\s*$", re.MULTILINE)
PLACEHOLDER_RE = re.compile(r"\[(?:TODO|확인 필요|작성 필요|[^]\n]{0,80})\]", re.IGNORECASE)


def _normalize_heading(value: str) -> str:
    value = re.sub(r"[`*_]", "", value).strip().casefold()
    value = re.sub(r"\s+", " ", value)
    return value.rstrip(":：")


def technical_document_messages(metadata: Mapping[str, Any], body: str) -> tuple[list[str], list[str]]:
    """Return type-specific errors and review warnings without changing the document."""

    doc_type = str(metadata.get("type", ""))
    if doc_type not in TECHNICAL_DOCUMENT_TYPES:
        return [], []
    if doc_type == "reference" and metadata.get("technical_writing") is not True and not isinstance(metadata.get("context"), Mapping):
        return [], []
    headings = {_normalize_heading(value) for value in HEADING_RE.findall(body)}
    errors: list[str] = []
    for required in REQUIRED_SECTIONS[doc_type]:
        aliases = SECTION_ALIASES.get(required.casefold(), {required.casefold()})
        if not headings.intersection({_normalize_heading(alias) for alias in aliases}):
            errors.append(f"{doc_type} requires section {required!r}")
    context = metadata.get("context")
    if not isinstance(context, Mapping):
        errors.append(f"{doc_type} requires context metadata")
    governance = metadata.get("governance")
    if not isinstance(governance, Mapping):
        errors.append(f"{doc_type} requires governance metadata")
    warnings: list[str] = []
    if PLACEHOLDER_RE.search(body) and metadata.get("status") == "active":
        warnings.append("active technical document still contains placeholder text")
    return errors, warnings


def template_body(doc_type: str, title: str) -> str:
    if doc_type not in TECHNICAL_DOCUMENT_TYPES:
        raise ValueError(f"unsupported technical document type: {doc_type}")
    sections = REQUIRED_SECTIONS[doc_type]
    parts = [f"# {title}", ""]
    for section in sections:
        parts.extend([f"## {section}", "[TODO]", ""])
    return "\n".join(parts).rstrip() + "\n"
