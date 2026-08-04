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

- 모든 저장소 작업 요청에서 사용자가 과거 결정, 문서 이름이나 경로를 기억한다고 가정하지 않는다. LMWiki 스킬은 실질적인 조사·판단·수정 또는 최종 답변 전에 요청과 작업 경로를 질의로 만들어 `query search`를 실행하고, 관련 후보를 `query read`로 직접 읽어 적용한다.
- 같은 작업 단위에서 이미 읽은 근거가 요청을 충분히 포괄하면 재사용할 수 있지만, 주제나 대상 경로가 달라지면 다시 검색한다. 자동 조회는 읽기 전용이며 기억 저장, 동기화 또는 재색인 승인을 뜻하지 않는다.
- L0–L3 개인 기억과 Persona는 기본적으로 `.knowledge/private-memory/`에 둔다.
- 팀 공유가 확인된 L2 기억만 `docs/memory/l2/`에 둔다.
- LMWiki 스킬은 작업 완료 후보를 판단한 뒤 사용자에게 기억 저장 여부를 묻고, 사용자가 다음 메시지에서 확인한 경우에만 L0–L2를 순서대로 처리한다. Stop 훅은 기억 저장 트리거로 사용하지 않는다. L3는 `query l3-candidates`가 같은 subject의 활성 L1/L2 근거를 두 개 이상 반환할 때만 독립성을 검토한다.
- 완료·commit·push·pull request 같은 인수인계 경계 신호가 보이면 AI가 같은 작업 단위에서 runbook 생성 여부를 한 번 묻는다. 사용자가 `만들기`를 선택한 뒤에만 `draft`를 만든다.
- 조회 시 호출자의 `user:*`, `team:*`, `role:*`, `agent:*` 주체를 확인하고 ACL 필터를 먼저 적용한다.
- 저장소 고유 명칭은 `docs/vocabulary/glossary.yml`에서 확인하고 `query glossary`로 조회한다.
- `query`는 읽기 전용이다. `manage sync/reindex/migrate`는 등록된 manager가 사용자 허락을 받은 뒤에만 `--apply`를 사용한다.

## 하위 지도

- 아직 없음 — 주요 영역이 루트 지도에서 2단계를 넘을 때 추가한다.

## 변경 규칙

- 계약이 적용되는 코드를 바꾸면 관련 계약과 검증 근거를 함께 검토한다.
- 저장소 고유 명칭을 새로 도입하거나 뜻을 바꾸면 용어집을 함께 갱신한다.
