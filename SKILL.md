---
name: repository-knowledge-steward
description: Manage code and Markdown knowledge together with AGENTS.md maps, typed contracts, decisions, runbooks, controlled vocabulary, lifecycle metadata, validation, and optional embedding retrieval. Use when bootstrapping repository documentation, mapping a large codebase, changing code that may affect documentation, auditing stale or conflicting knowledge, defining Markdown frontmatter, or configuring semantic search over repository documents.
---

# 저장소 지식 관리

`AGENTS.md`를 탐색 지도, 메타데이터가 있는 Markdown을 권위 있는 자료로 사용한다. 코드 변경 전 관련 계약을 찾고 변경 후 문서·관계·검증 근거가 함께 유지되는지 확인한다.

## 1. 권한과 모드 결정

사용자 요청에서 가장 권한이 적은 모드를 선택한다.

- `bootstrap`: 지식 구조 생성을 요청한 경우
- `change`: 코드나 문서 수정을 요청한 경우
- `audit`: 설명, 진단, 검토만 요청한 경우
- `reindex`: 임베딩 색인 생성·갱신을 요청한 경우

`audit`에서는 파일을 수정하지 않는다. `change`에서는 요청 범위 안의 코드와 관련 문서만 수정한다.

## 2. 임베딩 의향 확인

저장소의 `.knowledge/config.yml`을 먼저 확인한다. 설정이 없고 사용자가 `bootstrap` 또는 지식 관리 설정을 요청했다면 다음 질문을 한 번 묻는다.

> 이 저장소의 문서 검색에 임베딩 색인을 사용하시겠습니까? 임베딩을 사용하지 않아도 메타데이터, 통제어휘, 경로와 문서 관계를 이용한 검색은 동작합니다.

- 답하지 않거나 거절하면 `embedding.enabled: false`로 설정한다.
- 사용하면 저장소의 기존 embedding provider, model, vector store와 환경 설정을 먼저 조사한다.
- 확인되지 않은 모델 ID를 만들지 않는다.
- 기존 구성이 없으면 문서를 외부 API로 전송해도 되는지 확인한다. 기본값은 `아니요`이다.
- 선택을 `.knowledge/config.yml`에 기록하고 설정이 바뀌기 전에는 다시 묻지 않는다.

임베딩을 사용하지 않으면 메타데이터·키워드·관계 검색으로 계속한다. 임베딩을 사용하면 [임베딩 검색](references/embedding-retrieval.md)을 읽는다.

## 3. 지식 탐색

1. 작업 경로에서 가장 가까운 `AGENTS.md`를 찾고 루트까지 읽는다.
2. 지도가 연결한 활성 계약과 검증 진입점을 수집한다.
3. `applies_to`가 작업 경로와 겹치는 문서를 찾는다.
4. 요청어를 `docs/vocabulary/topics.yml`의 표준 키와 이명으로 확장한다.
5. 임베딩이 활성화됐으면 앞의 필터 안에서 의미 검색 후보를 추가한다.
6. `depends_on`, `derived_from`, `verified_by`, `supersedes` 관계로 필수 읽기 집합을 확장한다.
7. 선택한 자료의 `authority`, `status`, `summary`와 관련 본문을 확인한다.

지도 작성·수정 시 [AGENTS.md 지도](references/agents-map.md)를 읽는다. 문서 frontmatter를 생성·수정할 때 [메타데이터 스키마](references/metadata-schema.md)를 읽는다.

## 4. 변경 작업

변경 전에 다음을 식별한다.

- 변경할 코드와 문서
- 적용되는 활성 계약
- 관련 결정
- 필요한 테스트 또는 수동 검증
- 예상되는 문서 변경

계약이 적용되는 코드를 바꾸면서 문서를 변경하지 않는다면 이유를 완료 보고에 남긴다. 계약을 대체하거나 폐기할 때 [생명주기와 관계](references/lifecycle-and-relations.md)를 읽는다.

## 5. 검증

관리 문서를 변경했거나 감사할 때 다음을 실행한다.

Windows PowerShell:

```powershell
$env:PYTHONUTF8='1'
python <skill-path>/scripts/validate_knowledge.py <repository-root>
```

macOS/Linux:

```bash
PYTHONUTF8=1 python <skill-path>/scripts/validate_knowledge.py <repository-root>
```

`yaml` module이 없으면 자동으로 설치하지 않는다. 사용자 승인을 받은 뒤 `python -m pip install -r <skill-path>/scripts/requirements.txt`를 실행한다.

오류가 있으면 완료로 보고하지 않는다. 경고는 자동으로 내용을 바꾸지 말고 원인과 처리 여부를 보고한다.

임베딩이 활성화됐고 관리 문서가 변경됐으면 청크 manifest를 갱신한다.

```powershell
$env:PYTHONUTF8='1'
python <skill-path>/scripts/build_embedding_index.py <repository-root>
```

macOS/Linux에서는 `PYTHONUTF8=1 python <skill-path>/scripts/build_embedding_index.py <repository-root>`를 실행한다.

이 스크립트는 provider 중립적인 JSONL 청크를 만든다. 실제 벡터 계산과 저장은 확인된 저장소 구성에 연결한다.

## 6. 완료 보고

다음 형식으로 영향과 검증을 짧게 보고한다.

```md
## 지식 영향

- 적용한 계약: `<document-id>`
- 갱신한 문서: `<path>`
- 유지하거나 대체한 결정: `<document-id>`
- 실행한 검증: `<command and result>`
- 문서 영향 없음: `<해당하는 경우 근거>`
```

## 7. Bootstrap 산출물

사용자가 지식 구조 생성을 승인한 경우에만 `assets/templates/`를 바탕으로 다음을 만든다.

- 루트 `AGENTS.md`
- `docs/contracts/`, `docs/decisions/`, `docs/runbooks/`, `docs/concepts/`, `docs/references/`
- `docs/vocabulary/topics.yml`
- `.knowledge/config.yml`

기존 `AGENTS.md`나 문서를 덮어쓰지 않는다. 내용을 읽고 필요한 섹션과 frontmatter만 병합한다.
