---
id: MAP-ROOT-001
title: 저장소 지식 지도
type: map
status: active
authority: normative
topics:
  - repository-knowledge-management
summary: 저장소의 코드 영역과 필수 계약 및 검증 진입점을 연결한다.
applies_to:
  - "**"
read_when:
  - 저장소 작업을 시작할 때
relations: []
reviewed: YYYY-MM-DD
embedding:
  mode: local_only
  content: full
---

# 저장소 지식 지도

## 관할 범위

- 저장소 전체. 구축 과정에서 더 구체적인 하위 지도를 추가한다.

## 영역별 시작점

- 아직 없음 — 저장소 조사 후 실제 코드·문서 경로를 기록한다.

## 필수 계약

- 아직 없음 — 활성 계약을 만든 뒤 문서 ID와 상대 경로를 기록한다.

## 검증

- 아직 없음 — 저장소에서 확인한 테스트·린트·수동 검증 명령을 기록한다.

## 기억과 조회

- L0–L3 개인 기억과 Persona는 기본적으로 `.knowledge/private-memory/`에 둔다.
- 팀 공유가 확인된 L2 기억만 `docs/memory/l2/`에 둔다.
- 조회 시 호출자의 `user:*`, `team:*`, `role:*`, `agent:*` 주체를 확인하고 ACL 필터를 먼저 적용한다.
- `query`는 읽기 전용이다. `manage sync/reindex/migrate`는 등록된 manager가 사용자 허락을 받은 뒤에만 `--apply`를 사용한다.

## 하위 지도

- 아직 없음 — 주요 영역이 루트 지도에서 2단계를 넘을 때 추가한다.

## 변경 규칙

- 계약이 적용되는 코드를 바꾸면 관련 계약과 검증 근거를 함께 검토한다.
