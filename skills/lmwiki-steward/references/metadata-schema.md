# Markdown 메타데이터 스키마

## 최소 예시

```yaml
---
id: CONTRACT-AUTH-001
title: 인증 토큰 계약
type: contract
status: active
authority: normative
topics:
  - authentication
summary: 인증 토큰의 발급, 검증, 만료 조건을 정의한다.
applies_to:
  - src/auth/**
read_when:
  - 인증 코드를 변경할 때
relations:
  - type: verified_by
    target: tests/auth/token.test.ts
reviewed: YYYY-MM-DD
embedding:
  mode: local_only
  content: full
---
```

## 필드

| 필드 | 필수 | 값 |
| --- | :---: | --- |
| `id` | 예 | 저장소에서 유일한 영구 식별자 |
| `title` | 예 | 현재 표시 제목 |
| `type` | 예 | `map`, `contract`, `decision`, `runbook`, `concept`, `reference`, `memory`, `persona` |
| `status` | 예 | `draft`, `active`, `deprecated`, `archived` |
| `authority` | 예 | `normative`, `informative`, `generated` |
| `topics` | 예 | 통제어휘의 표준 키 배열 |
| `summary` | 예 | 독립적으로 이해되는 1~2문장 |
| `applies_to` | 조건부 | `map`, `contract`, `runbook`의 적용 glob |
| `read_when` | 조건부 | `map`, `contract`, `runbook`을 읽을 구체적 상황 |
| `relations` | 예 | 관계 객체 배열, 없으면 `[]` |
| `reviewed` | 예 | 내용 검증일 `YYYY-MM-DD` |
| `memory` | 기억만 | `level`, `subject`, `confidence` |
| `access` | 기억만 | `visibility`, `owner`, `team`, `grants` |
| `provenance` | 아니요 | 원문 경로와 관계를 담은 문자열 또는 객체 배열 |
| `embedding.mode` | 아니요 | `allow`, `local_only`, `deny`; 기본 `local_only` |
| `embedding.content` | 아니요 | `full`, `summary_only`; 기본 `full` |

`created`, `updated`, `author`는 Git과 중복되므로 기본 스키마에 넣지 않는다. `reviewed`는 편집 시각이 아니라 내용이 현재 기준과 일치함을 확인한 날짜다.

## 기억과 접근 제어

- `memory.level`: `l0`, `l1`, `l2`, `l3`
- `memory.confidence`: 0부터 1 사이의 수
- `access.visibility`: `private`, `team`, `restricted`, `agent`
- 주체: `user:*`, `role:*`, `agent:*`, `team:*`
- grant 권한: `read`, `write`, `manage`

L1–L3 기억은 `distilled_from` 관계를 가진다. Persona는 L3이며 기본적으로 서로 다른 근거 두 개 이상을 요구한다. `private`와 `restricted`는 Git ACL이 아니므로 로컬 비추적 기억 경로에 저장한다.

## 식별자

`<TYPE>-<SCOPE>-<NNN>` 형식을 권장한다.

```text
MAP-ROOT-001
CONTRACT-AUTH-001
DECISION-AUTH-001
RUNBOOK-AUTH-001
CONCEPT-AUTH-001
REFERENCE-API-001
```

파일 이동, 제목 변경, 번역으로 ID를 바꾸지 않는다. 폐기한 ID를 재사용하지 않는다.

## 통제어휘

`docs/vocabulary/topics.yml`에서 대표 키와 이명을 관리한다.

```yaml
authentication:
  label: 인증
  aliases:
    - auth
    - login
    - 사용자 인증
```

문서의 `topics`에는 대표 키만 기록한다. 하나의 이명을 여러 대표 키에 등록하지 않는다.
