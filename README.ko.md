# LMWiki

[English](README.md) | [한국어](README.ko.md)

AI가 코드를 늘리는 속도에 비해 문서는 금방 낡습니다. LMWiki는 저장소 지도, 계약, 결정, runbook, 계층형 기억, Persona와 검증 근거를 코드에 연결해 관리합니다.

스킬은 `$lmwiki` 하나입니다. 저장소 상태와 요청에 따라 구축, 도입, 변경, 감사, 기억 또는 재색인 모드를 고르고 해당 모드에 필요한 세부 규칙만 읽습니다.

LMWiki를 처음 구축할 때 임베딩과 로컬 SQLite BM25 위치 색인을 사용할지 한 번 묻습니다. 답은 `.knowledge/config.yml`에 저장하고 이후 실행에서는 다시 묻지 않습니다.

## 관리하는 정보

- `AGENTS.md`는 코드 영역, 활성 계약과 검증 명령을 연결합니다.
- Markdown frontmatter에는 문서 ID, 유형, 상태, 주제, 적용 범위와 관계를 기록합니다.
- 통제어휘는 `auth`, `login` 같은 이명을 하나의 주제 키에 연결합니다.
- 검증기는 중복 ID, 끊어진 링크, 잘못된 상태 의존과 검증 근거가 없는 활성 계약을 찾습니다.
- L0–L3는 대화 원문, 단일 사실, 작업 장면과 장기 Persona를 분리합니다.
- 사용자·팀·역할·에이전트 정책은 검색 점수를 계산하기 전에 조회 범위를 거릅니다.
- 읽기 전용 `query` 명령과 파일을 바꿀 수 있는 `manage` 명령을 분리합니다.
- 임베딩을 허용하면 로컬 SQLite FTS5/BM25 색인이 관련 문서 위치를 넓게 찾습니다. Markdown 원본을 대체하지 않습니다.

## 설치

[Skills CLI](https://github.com/vercel-labs/skills)로 설치합니다.

```powershell
npx skills add j-token/lmwiki --skill lmwiki
```

Codex 전역에 복사 설치하려면 다음 명령을 사용합니다.

```powershell
npx skills add j-token/lmwiki --skill lmwiki -g -a codex -y --copy
```

## 사용

LMWiki 구조가 없는 저장소의 최초 구축에 사용합니다.

```text
$lmwiki를 사용해서 이 저장소를 초기화하고 기존 문서도 이관해줘.
```

구축 이후의 변경에도 같은 스킬을 사용합니다.

```text
$lmwiki를 사용해서 인증 흐름을 수정하고 관련 계약과 runbook도 같이 관리해줘.
```

루트 `SKILL.md`에는 모드 선택과 공통 안전 경계만 둡니다. 도입, 접근 제어, 메타데이터, 기억, 생명주기와 임베딩 세부 규칙은 직접 연결된 reference에 두고 관련 작업에서만 읽습니다.

## 문서 유형

문서는 8가지 유형으로 나눕니다.

| 유형 | 역할 |
| --- | --- |
| `map` | 코드 영역과 문서·검증 진입점 연결 |
| `contract` | 시스템이 지켜야 하는 동작과 제약 기록 |
| `decision` | 선택 이유와 대체 이력 기록 |
| `runbook` | 운영·복구 절차 기록 |
| `concept` | 저장소에서 사용하는 개념과 작동 원리 설명 |
| `reference` | 코드에서 생성했거나 외부에서 가져온 참조 정보 보관 |
| `memory` | L0–L2 대화·작업 기억 보관 |
| `persona` | 여러 근거에서 확인된 L3 장기 협업 선호 보관 |

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

기억 문서에는 계층과 접근 정책도 기록합니다.

```yaml
memory:
  level: l2
  subject: project:repository
  confidence: 0.8
access:
  visibility: team
  owner: user:owner
  team: team:repository
  grants:
    - subject: agent:lmwiki
      permissions: [read]
```

## 저장소 구조

스킬은 대상 저장소에 다음 구조를 만들고 관리합니다.

```text
AGENTS.md
.knowledge/
├── config.yml
├── purpose.md
├── schema.md
├── principals.yml
├── index/
│   └── .gitignore
└── private-memory/
    ├── l0/
    ├── l1/
    ├── l2/
    └── l3/
docs/
├── contracts/
├── decisions/
├── runbooks/
├── concepts/
├── references/
├── memory/
│   └── l2/
└── vocabulary/
    └── topics.yml
```

루트 지도에서 주요 코드 영역까지 2번 이하의 지도 링크로 도달하게 합니다. 하위 지도는 루트 규칙을 복사하지 않고 해당 영역의 정보만 추가합니다.

## 기억과 접근 범위

- L0는 대화 원문 근거를 보존합니다.
- L1은 사실·선호·제약·사건 하나를 기록합니다.
- L2는 프로젝트나 작업 장면을 복원합니다.
- L3 Persona는 서로 다른 L1 또는 L2 근거가 두 개 이상일 때만 만듭니다.

기억 캡처 기본값은 `explicit`입니다. 개인·제한 기억은 Git에서 제외되는 `.knowledge/private-memory/`에 둡니다. frontmatter ACL은 에이전트 조회를 거르는 정책이며, 저장소를 읽을 수 있는 사람의 파일 접근을 차단하지는 못합니다.

## 조회와 관리

```powershell
$env:PYTHONUTF8='1'
python skills/lmwiki/scripts/knowledge_cli.py query search <repository-root> "인증" --principal user:owner --team team:repository
python skills/lmwiki/scripts/knowledge_cli.py query graph <repository-root> --principal user:owner --team team:repository
```

`query search`, `read`, `list`, `graph`는 파일을 변경하지 않습니다. `manage validate`도 읽기 전용입니다. `manage sync`, `reindex`, `migrate`는 호출 주체가 `access_control.managers`에 있어야 하며, `--apply`가 있어야 저장소를 변경합니다.

검색은 짧고 정확한 답보다 관련 문서를 놓치지 않는 쪽을 택합니다. 임베딩을 켜면 통제어휘 이명, 접두어와 한국어 2글자 토큰을 확장해 BM25 후보를 최대 24개 찾고, 관계를 1 hop 따라간 뒤 위치를 최대 12개 반환합니다. 결과에는 `path`, `id`, `rank`, `via`, `engine`만 들어가며 LLM이 선택한 문서를 `query read`로 직접 읽어야 합니다.

## 임베딩

최초 구축에서는 구조를 만들기 전에 명시적인 예/아니요 답을 기다립니다. 예라고 답하면 로컬 임베딩과 SQLite BM25를 기본으로 켭니다. 아니요라고 답하면 둘 다 끄되 메타데이터·통제어휘·키워드·경로·관계 검색은 유지합니다. 답은 `.knowledge/config.yml`에 저장하므로 이후에는 다시 묻지 않습니다.

문서 외부 전송은 기본적으로 꺼져 있습니다. `local_only` 문서는 로컬에서만 처리하고 `deny` 문서는 청크 manifest에서도 제외합니다. Markdown이 원본이며 벡터 색인은 삭제한 뒤 다시 만들 수 있습니다.

포함된 색인기는 provider와 무관한 JSONL 청크와 로컬 SQLite FTS5/BM25 데이터베이스를 만듭니다. 데이터베이스는 임베딩을 켠 경우에만 사용하고 Git에서 제외하며 삭제 후 다시 만들 수 있습니다. ACL로 허용된 문서 ID를 먼저 고른 다음 BM25 순위를 계산합니다. 실제 모델과 벡터 저장소는 대상 저장소의 기존 구성을 우선합니다. 확인하지 않은 모델 ID를 만들거나 실패 후 다른 원격 provider로 자동 전환하지 않습니다.

## 검증

Python과 PyYAML이 필요합니다. `python3`가 아니라 `python` 명령을 사용합니다.

이 저장소에서 신규 구조를 만들 때는 다음 명령을 사용합니다.

```powershell
$env:PYTHONUTF8='1'
python skills/lmwiki/scripts/bootstrap_lmwiki.py <repository-root> --embedding local
```

최초 질문에 아니요라고 답하면 `--embedding disabled`를 사용합니다.

기존 LMWiki 저장소를 검증합니다.

```powershell
$env:PYTHONUTF8='1'
python skills/lmwiki/scripts/validate_knowledge.py <repository-root>
```

임베딩을 사용하면 청크 manifest와 SQLite 검색 색인을 생성합니다.

```powershell
$env:PYTHONUTF8='1'
python skills/lmwiki/scripts/build_embedding_index.py <repository-root>
python skills/lmwiki/scripts/build_search_index.py <repository-root>
```

## 현재 한계

- 임베딩 색인기는 청크와 해시를 만듭니다. 실제 모델·벡터 저장소 연결은 저장소별 구현이 필요합니다.
- SQLite 검색은 Python에 포함된 SQLite의 FTS5 지원이 필요하며 snippet이나 생성 답변이 아닌 후보 위치만 반환합니다.
- 문서 검토 경고의 기본값은 180일입니다. 날짜가 지났다는 이유로 문서를 자동 폐기하지 않습니다.
- Python 의존성은 PyYAML 1개입니다.
- Git에 기록한 ACL 메타데이터는 저장소 독자에 대한 기밀성을 제공하지 않습니다. 강제 집행에는 비공개 저장소나 인증된 외부 backend가 필요합니다.

메타데이터 필드와 검색 임계값은 초기값입니다. 실제 저장소에 적용하면서 너무 엄격하거나 느슨한 부분은 바꿀 예정입니다.
