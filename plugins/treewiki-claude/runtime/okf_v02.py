from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence


OKF_VERSION = "0.2"
STATUS_TO_OKF = {
    "proposed": "draft",
    "draft": "draft",
    "active": "stable",
    "deprecated": "deprecated",
    "superseded": "deprecated",
    "rejected": "deprecated",
    "archived": "deprecated",
}
STATUS_FROM_OKF = {"draft": "draft", "stable": "active", "deprecated": "deprecated"}


class OkfError(ValueError):
    pass


def _actor_for(metadata: Mapping[str, Any]) -> str:
    sharing = metadata.get("sharing") if isinstance(metadata.get("sharing"), Mapping) else {}
    authored = sharing.get("authored_by")
    if isinstance(authored, str) and authored.startswith("user:"):
        return "human:" + authored.split(":", 1)[1]
    if isinstance(authored, str) and authored.startswith("agent:"):
        return "treewiki/0.2.0"
    return "treewiki/0.2.0"


def _sources(metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    relations = metadata.get("relations")
    if isinstance(relations, list):
        for relation in relations:
            if not isinstance(relation, Mapping) or relation.get("type") not in {
                "derived_from",
                "distilled_from",
                "verified_by",
            }:
                continue
            target = relation.get("target")
            if isinstance(target, str) and target:
                result.append({"id": target, "resource": f"treewiki:{target}"})
    provenance = metadata.get("provenance")
    if isinstance(provenance, list):
        for index, item in enumerate(provenance, start=1):
            source = item if isinstance(item, str) else item.get("source") if isinstance(item, Mapping) else None
            if isinstance(source, str) and source:
                result.append({"id": f"source-{index}", "resource": source})
    deduplicated: dict[tuple[str, str], dict[str, Any]] = {}
    for item in result:
        deduplicated[(str(item.get("id", "")), str(item["resource"]))] = item
    return list(deduplicated.values())


def export_concept(
    metadata: Mapping[str, Any],
    body: str,
    history: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    doc_type = metadata.get("type")
    if not isinstance(doc_type, str) or not doc_type:
        raise OkfError("TreeWiki document requires type")
    result: dict[str, Any] = {
        "type": doc_type,
        "title": metadata.get("title"),
        "description": metadata.get("summary"),
        "tags": copy.deepcopy(metadata.get("topics", [])),
        "status": STATUS_TO_OKF.get(str(metadata.get("status")), "draft"),
    }
    modified_at = metadata.get("modified_at")
    if isinstance(modified_at, str) and modified_at:
        result["generated"] = {"by": _actor_for(metadata), "at": modified_at}
    sources = _sources(metadata)
    if sources:
        result["sources"] = sources
    verified = [
        {"by": str(event.get("actor")), "at": str(event.get("at"))}
        for event in history
        if event.get("event") == "verified" and event.get("actor") and event.get("at")
    ]
    if verified:
        result["verified"] = verified
    treewiki_extension = copy.deepcopy(dict(metadata))
    result["treewiki"] = treewiki_extension
    return {
        "okf_version": OKF_VERSION,
        "frontmatter": result,
        "body": body,
    }


def import_concept(
    concept: Mapping[str, Any],
    *,
    document_id: str,
    owner: str,
    team: str,
) -> tuple[dict[str, Any], str]:
    if concept.get("okf_version") not in {None, "0.1", OKF_VERSION}:
        raise OkfError("unsupported OKF version")
    frontmatter = concept.get("frontmatter")
    if not isinstance(frontmatter, Mapping):
        raise OkfError("OKF concept requires a frontmatter mapping")
    doc_type = frontmatter.get("type")
    if not isinstance(doc_type, str) or not doc_type:
        raise OkfError("OKF type is required")
    extension = frontmatter.get("treewiki")
    metadata = copy.deepcopy(dict(extension)) if isinstance(extension, Mapping) else {}
    metadata.update(
        {
            "id": document_id,
            "title": frontmatter.get("title") or document_id,
            "type": doc_type,
            "status": STATUS_FROM_OKF.get(str(frontmatter.get("status", "stable")), "draft"),
            "authority": metadata.get("authority", "informative"),
            "topics": copy.deepcopy(frontmatter.get("tags", [])),
            "summary": frontmatter.get("description") or "Imported OKF concept.",
            "relations": copy.deepcopy(metadata.get("relations", [])),
            "access": copy.deepcopy(
                metadata.get(
                    "access",
                    {
                        "visibility": "team",
                        "owner": owner,
                        "team": team,
                        "grants": [],
                    },
                )
            ),
        }
    )
    generated = frontmatter.get("generated")
    if isinstance(generated, Mapping) and isinstance(generated.get("at"), str):
        metadata["modified_at"] = generated["at"]
    body = concept.get("body", "")
    if not isinstance(body, str):
        raise OkfError("OKF body must be a string")
    return metadata, body
