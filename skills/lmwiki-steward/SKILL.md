---
name: lmwiki-steward
description: 기존 LMWiki 저장소에서 코드·문서 변경과 L0–L3 기억, Persona, 사용자·팀·역할·에이전트 ACL을 추적하고 ACL 우선 SQLite BM25 위치 조회와 승인 기반 관리 명령을 실행합니다. 일상 변경, 기억 증류, 오래된 지식 감사, 계약 생명주기, 관계 복구, 동기화와 재색인에 사용합니다. LMWiki 설정과 지도가 없으면 초기화하지 않고 lmwiki-builder를 사용합니다.
---

# LMWiki 관리

이미 구축된 LMWiki에서 코드 변경 전 권한이 있는 지식을 찾고, 변경 후 계약·결정·운영 문서·기억과 검색 색인을 함께 유지한다. 초기 구조를 생성하거나 재설계하지 않는다.

## 1. 전제와 권한

루트 `AGENTS.md`와 `.knowledge/config.yml`을 먼저 확인한다. 둘 중 하나가 없으면 임의로 만들지 말고 `$lmwiki-builder`가 필요한 상태라고 보고한다.

사용자 요청에서 가장 권한이 적은 모드를 선택한다.

- `change`: 코드나 문서 변경
- `audit`: 읽기·진단·검토만 수행
- `reindex`: 파생 색인만 갱신
- `memory`: 동의된 대화에서 L0–L3 기억 또는 Persona 갱신

`audit`에서는 파일을 수정하지 않는다. `change`에서는 요청 범위와 그 변경에 직접 영향받는 문서만 수정한다.

## 2. 조회 권한 결정

[접근 제어](references/access-control.md)와 [조회와 관리 명령](references/command-boundaries.md)을 읽는다. 현재 `user:*`, `team:*`, 선택적 `role:*`, `agent:*` 주체를 저장소 설정이나 사용자에게서 확인한다. 알 수 없는 주체를 만들거나 다른 사용자를 사칭하지 않는다.

조회는 다음 CLI를 우선한다.

```powershell
$env:PYTHONUTF8='1'
python <skill-path>/scripts/knowledge_cli.py query search <repository-root> "<query>" --principal user:<id> --team team:<id> --agent agent:<id>
```

`query search`, `read`, `list`, `graph`는 읽기 전용이며 권한 필터를 검색보다 먼저 적용한다. `search`는 관련 후보의 위치만 반환하므로 필요한 경로의 본문은 별도 `query read`로 연다.

## 3. 작업 지식 찾기

1. 작업 경로에서 가장 가까운 `AGENTS.md`와 루트까지의 상위 지도를 읽는다.
2. 지도에서 지정한 활성 계약과 검증 진입점을 수집한다.
3. `applies_to`가 작업 경로와 겹치는 문서를 찾는다.
4. 요청어를 통제어휘의 표준 키와 이명으로 확장한다.
5. 임베딩이 활성화됐으면 ACL 허용 집합 안에서 고재현율 SQLite BM25 후보를 최대 24개 수집한다.
6. `depends_on`, `derived_from`, `verified_by`, `supersedes` 관계를 따라 필수 읽기 집합을 확장한다.
7. `authority`, `status`, `summary`와 관련 본문을 확인한다.

지도 변경 시 [AGENTS.md 지도](references/agents-map.md), frontmatter 변경 시 [메타데이터 스키마](references/metadata-schema.md)를 읽는다. 임베딩이 활성화된 경우에만 [임베딩 검색](references/embedding-retrieval.md)을 읽는다.

## 4. 변경 영향 관리

변경 전에 다음을 내부 작업 목록으로 만든다.

- 변경할 코드와 문서
- 적용되는 활성 계약
- 관련 결정과 운영 절차
- 필요한 테스트 또는 수동 검증
- 예상되는 문서·지도·색인 변경

계약이 적용되는 코드를 바꾸면서 문서를 변경하지 않으면 이유를 완료 보고에 남긴다. 새 문서는 `assets/`의 유형별 템플릿을 사용하되 ID, 주제, 적용 범위와 관계를 실제 저장소에 맞게 바꾼다.

## 5. 기억과 Persona

`memory` 작업에서는 [기억 계층과 Persona](references/memory-and-persona.md)를 읽는다.

- `memory.capture: explicit`이면 사용자의 저장 요청이나 기존 동의가 없을 때 L0를 만들지 않는다.
- L0는 원문을 보존하고, L1은 한 가지 사실·선호·제약만 담는다.
- L2는 특정 작업 장면을 복원할 정보만 모은다.
- L3 Persona는 서로 다른 근거 두 개 이상에서 반복 확인된 협업 선호만 담는다.
- 새 근거가 기존 기억과 충돌하면 덮어쓰지 않고 `supersedes`와 반증 근거를 기록한다.
- 개인·제한 기억은 로컬 비추적 경로에 유지한다.

## 6. 계약 생명주기

계약이나 결정을 대체·폐기·복구할 때 [생명주기와 관계](references/lifecycle-and-relations.md)를 읽는다.

- 삭제보다 `draft → active → deprecated → archived` 상태 전이를 사용한다.
- 새 문서가 이전 문서를 대체하면 `supersedes`를 기록한다.
- 활성 계약에는 `verified_by`를 최소 1개 유지한다.
- 활성 문서가 폐기 문서에 `depends_on`하지 않게 한다.
- 파일 이동이나 제목 변경으로 문서 ID를 바꾸지 않는다.

## 7. 검증과 관리 명령

Windows PowerShell:

```powershell
$env:PYTHONUTF8='1'
python <skill-path>/scripts/validate_knowledge.py <repository-root>
```

macOS/Linux:

```bash
PYTHONUTF8=1 python <skill-path>/scripts/validate_knowledge.py <repository-root>
```

PyYAML이 없으면 자동 설치하지 않는다. 사용자 승인을 받은 뒤 `python -m pip install -r <skill-path>/scripts/requirements.txt`를 실행한다.

오류가 있으면 완료로 보고하지 않는다. 경고는 원인과 처리 여부를 보고하되 날짜 경과만으로 문서를 자동 폐기하지 않는다.

관리 문서가 변경됐고 `.knowledge/config.yml`에서 임베딩이 활성화됐으면 다음을 실행한다.

```powershell
$env:PYTHONUTF8='1'
python <skill-path>/scripts/build_embedding_index.py <repository-root>
python <skill-path>/scripts/build_search_index.py <repository-root>
```

실제 벡터 계산은 확인된 provider adapter로 수행한다. 사용자 허용 없이 문서를 외부 API로 전송하거나 다른 provider로 자동 전환하지 않는다.

통합 관리 명령은 다음 경계를 따른다.

- `manage validate`: 읽기 전용
- `manage sync`: 출처 해시와 영향 문서를 계산하며 `--apply` 시 registry 갱신
- `manage reindex`: `--apply` 시 청크 manifest와 SQLite BM25 파생 색인 갱신
- `manage migrate`: `--apply` 시 빠진 설정과 기억 디렉터리만 추가

파일을 바꾸는 관리 명령은 `access_control.managers`에 등록된 호출 주체만 실행한다. 사용자가 해당 변경을 허락한 뒤에만 `--apply`를 전달한다.

## 8. 완료 보고

```md
## LMWiki 영향

- 적용한 계약: `<document-id>`
- 갱신한 문서와 지도: `<paths>`
- 유지하거나 대체한 결정: `<document-id>`
- 실행한 검증: `<command and result>`
- 색인 변경: `<reused/new/removed chunks, BM25 documents>`
- 기억 변경: `<L0/L1/L2/L3, provenance, supersedes>`
- 접근 범위: `<visibility, owner/team, grants>`
- 문서 영향 없음: `<해당하는 경우 근거>`
```

구조 재구축이나 기존 문서 대량 이관이 필요해지면 현재 변경에 섞지 말고 `$lmwiki-builder` 작업으로 분리한다.
