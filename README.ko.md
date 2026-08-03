# LMWiki

[English](README.md) | [한국어](README.ko.md)

AI가 코드를 늘리는 속도에 비해 문서는 금방 낡습니다. LMWiki는 코드와 같은 Git 이력 안에서 저장소 지도, 계약, 결정, runbook과 검증 근거를 관리합니다.

스킬은 두 개로 나눴습니다. `lmwiki-builder`는 최초 구조 생성과 기존 문서 이관을 담당합니다. `lmwiki-steward`는 구축 이후의 일상 변경을 관리합니다.

## 관리하는 정보

- `AGENTS.md`는 코드 영역, 활성 계약과 검증 명령을 연결합니다.
- Markdown frontmatter에는 문서 ID, 유형, 상태, 주제, 적용 범위와 관계를 기록합니다.
- 통제어휘는 `auth`, `login` 같은 이명을 하나의 주제 키에 연결합니다.
- 검증기는 중복 ID, 끊어진 링크, 잘못된 상태 의존과 검증 근거가 없는 활성 계약을 찾습니다.
- 선택적 임베딩 manifest는 의미 검색을 추가합니다. Markdown 원본을 대체하지 않습니다.

## 설치

[Skills CLI](https://github.com/vercel-labs/skills)로 두 스킬을 설치합니다.

```powershell
npx skills add j-token/lmwiki --skill lmwiki-builder --skill lmwiki-steward
```

Codex 전역에 복사 설치하려면 다음 명령을 사용합니다.

```powershell
npx skills add j-token/lmwiki --skill lmwiki-builder --skill lmwiki-steward -g -a codex -y --copy
```

각 스킬을 따로 설치할 수도 있습니다.

```powershell
npx skills add j-token/lmwiki --skill lmwiki-builder
npx skills add j-token/lmwiki --skill lmwiki-steward
```

## 사용

LMWiki 구조가 없는 저장소에는 builder를 사용합니다.

```text
$lmwiki-builder를 사용해서 이 저장소를 초기화하고 기존 문서도 이관해줘.
```

구축 이후에는 steward를 사용합니다.

```text
$lmwiki-steward를 사용해서 인증 흐름을 수정하고 관련 계약과 runbook도 같이 관리해줘.
```

| 스킬 | 작업 |
| --- | --- |
| `lmwiki-builder` | 신규 구축, 기존 문서 이관, 불완전 구조 복구, 임베딩 정책과 최초 색인 |
| `lmwiki-steward` | 코드·문서 변경, 감사, 생명주기 갱신, 관계 복구와 재색인 |

steward는 LMWiki 구조가 없을 때 임의로 초기화하지 않습니다. builder가 필요하다고 보고하고 멈춥니다.

## 문서 유형

문서는 6가지 유형으로 나눕니다.

| 유형 | 역할 |
| --- | --- |
| `map` | 코드 영역과 문서·검증 진입점 연결 |
| `contract` | 시스템이 지켜야 하는 동작과 제약 기록 |
| `decision` | 선택 이유와 대체 이력 기록 |
| `runbook` | 운영·복구 절차 기록 |
| `concept` | 저장소에서 사용하는 개념과 작동 원리 설명 |
| `reference` | 코드에서 생성했거나 외부에서 가져온 참조 정보 보관 |

관리 대상 Markdown은 YAML frontmatter로 시작합니다.

```yaml
---
id: CONTRACT-AUTH-001
title: 인증 토큰 계약
type: contract
status: active
authority: normative
topics:
  - authentication
summary: 인증 토큰의 발급, 검증과 만료 조건을 정의합니다.
applies_to:
  - src/auth/**
read_when:
  - 인증 코드를 변경할 때
relations:
  - type: verified_by
    target: tests/auth/token.test.ts
reviewed: 2026-08-03
embedding:
  mode: local_only
  content: full
---
```

## 저장소 구조

두 스킬은 대상 저장소에 다음 구조를 만들고 관리합니다.

```text
AGENTS.md
.knowledge/
└── config.yml
docs/
├── contracts/
├── decisions/
├── runbooks/
├── concepts/
├── references/
└── vocabulary/
    └── topics.yml
```

루트 지도에서 주요 코드 영역까지 2번 이하의 지도 링크로 도달하게 합니다. 하위 지도는 루트 규칙을 복사하지 않고 해당 영역의 정보만 추가합니다.

## 임베딩

builder는 최초 구축 시 임베딩을 사용할지 한 번 묻습니다. 거절하거나 답하지 않아도 메타데이터, 통제어휘, 경로와 문서 관계를 이용한 검색은 동작합니다.

문서 외부 전송은 기본적으로 꺼져 있습니다. `local_only` 문서는 로컬에서만 처리하고 `deny` 문서는 청크 manifest에서도 제외합니다. Markdown이 원본이며 벡터 색인은 삭제한 뒤 다시 만들 수 있습니다.

포함된 색인기는 provider와 무관한 JSONL 청크를 만듭니다. 실제 모델과 벡터 저장소는 대상 저장소의 기존 구성을 우선합니다. 확인하지 않은 모델 ID를 만들거나 실패 후 다른 원격 provider로 자동 전환하지 않습니다.

## 검증

Python과 PyYAML이 필요합니다. `python3`가 아니라 `python` 명령을 사용합니다.

이 저장소에서 신규 구조를 만들 때는 다음 명령을 사용합니다.

```powershell
$env:PYTHONUTF8='1'
python skills/lmwiki-builder/scripts/bootstrap_lmwiki.py <repository-root> --embedding disabled
```

기존 LMWiki 저장소를 검증합니다.

```powershell
$env:PYTHONUTF8='1'
python skills/lmwiki-steward/scripts/validate_knowledge.py <repository-root>
```

임베딩을 사용하면 청크 manifest를 생성합니다.

```powershell
$env:PYTHONUTF8='1'
python skills/lmwiki-steward/scripts/build_embedding_index.py <repository-root>
```

## 현재 한계

- 임베딩 색인기는 청크와 해시를 만듭니다. 실제 모델·벡터 저장소 연결은 저장소별 구현이 필요합니다.
- 문서 검토 경고의 기본값은 180일입니다. 날짜가 지났다는 이유로 문서를 자동 폐기하지 않습니다.
- Python 의존성은 PyYAML 1개입니다.

메타데이터 필드와 검색 임계값은 초기값입니다. 실제 저장소에 적용하면서 너무 엄격하거나 느슨한 부분은 바꿀 예정입니다.
