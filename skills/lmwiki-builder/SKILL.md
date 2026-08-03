---
name: lmwiki-builder
description: AGENTS.md 지도, 유형화된 Markdown, L0–L3 기억과 Persona, 사용자·팀·역할·에이전트 ACL, 조회/관리 명령, 검증과 선택적 임베딩·SQLite BM25 위치 검색으로 LMWiki 저장소 지식 체계를 구축하거나 도입합니다. 새 저장소 초기화, 기존 문서·대화 기억 이관, 불완전한 구조 복구, 접근 정책과 임베딩 선택, 최초 카탈로그 생성에 사용합니다. 구축 후 일상 관리는 lmwiki-steward를 사용합니다.
---

# LMWiki 구축

저장소의 기존 코드와 문서를 조사한 뒤 `AGENTS.md` 지도, 유형별 문서, 계층형 기억, 접근 정책, 통제어휘와 검증 설정을 처음 구축한다. 기존 자료를 덮어쓰지 않고 이관 계획과 검증 가능한 초기 상태를 만든다.

## 1. 구축 모드 결정

- `new`: 관리 구조가 없는 새 저장소
- `adopt`: 코드와 기존 문서가 있지만 LMWiki 구조가 없음
- `repair`: `.knowledge/config.yml` 또는 지도의 일부만 존재함

먼저 루트와 하위 `AGENTS.md`, Markdown, 코드 진입점, 테스트 명령과 Git 상태를 조사한다. 기존 구조로 알 수 있는 사실을 사용자에게 묻지 않는다.

## 2. 임베딩 의향 확인

`.knowledge/config.yml`에 선택이 없을 때 다음 질문을 한 번 묻는다.

> 이 저장소의 문서 검색에 임베딩 색인을 사용하시겠습니까? 임베딩을 사용하지 않아도 메타데이터, 통제어휘, 경로와 문서 관계를 이용한 검색은 동작합니다.

- 거절하거나 답하지 않으면 `disabled`로 구축한다.
- 사용하면 기존 provider, model, vector store와 환경 설정을 먼저 조사한다.
- 기존 구성이 없으면 저장소 문서를 외부 API로 전송해도 되는지 확인한다. 기본값은 `아니요`이다.
- 확인되지 않은 모델 ID를 만들지 않는다.
- 선택을 `.knowledge/config.yml`에 저장해 다시 묻지 않는다.

임베딩을 사용하면 [임베딩 검색](references/embedding-retrieval.md)을 읽는다.

## 3. 기억과 접근 범위 확인

[기억 계층과 Persona](references/memory-and-persona.md), [접근 제어](references/access-control.md), [조회와 관리 명령](references/command-boundaries.md)을 읽는다.

- 기억 캡처 기본값은 `explicit`이다. 기존 대화가 있다는 이유만으로 L0를 저장하지 않는다.
- 저장소 owner, team과 사용할 `user:*`, `role:*`, `agent:*` 주체를 확인한다.
- L0·L1·L3와 개인 L2는 `.knowledge/private-memory/`에 둔다.
- 팀이 공유하기로 확인한 L2만 `docs/memory/l2/`에 둔다.
- frontmatter ACL은 Git 독자를 막지 못한다고 사용자에게 알린다.
- 비밀, 인증 정보, 제3자 개인정보를 기억으로 이관하지 않는다.

## 4. 안전한 골격 생성

[도입 절차](references/adoption-workflow.md), [AGENTS.md 지도](references/agents-map.md), [메타데이터 스키마](references/metadata-schema.md)를 읽는다.

사용자가 구축을 요청한 경우 다음 스크립트로 없는 파일과 디렉터리만 만든다.

Windows PowerShell:

```powershell
$env:PYTHONUTF8='1'
python <skill-path>/scripts/bootstrap_lmwiki.py <repository-root> --embedding disabled --owner user:<id> --team team:<id>
```

macOS/Linux:

```bash
PYTHONUTF8=1 python <skill-path>/scripts/bootstrap_lmwiki.py <repository-root> --embedding disabled --owner user:<id> --team team:<id>
```

선택에 따라 `disabled`를 `local` 또는 `remote`로 바꾼다. `remote`는 사용자가 외부 전송을 명시적으로 허용했을 때만 `--remote-content-allowed`와 함께 사용한다.

스크립트가 건너뛴 기존 파일은 직접 읽고 필요한 frontmatter와 지도 섹션만 병합한다. 기존 내용을 덮어쓰거나 삭제하지 않는다.

## 5. 기존 자료 이관

1. 기존 Markdown을 `contract`, `decision`, `runbook`, `concept`, `reference`, `map` 후보로 분류한다.
2. 같은 사실을 설명하는 문서가 여럿이면 원본 후보와 중복 후보를 구분한다.
3. 안정적인 문서 ID와 통제 주제어를 부여한다.
4. 링크와 Git 이력을 보존할 수 있을 때만 파일을 유형별 폴더로 이동한다.
5. 코드 경로를 `applies_to`, 테스트를 `verified_by`, 결정 근거를 `derived_from`으로 연결한다.
6. 루트 지도에서 주요 코드 영역까지 2번 이하의 지도 링크로 도달하게 한다.
7. 대화 자료는 동의된 범위만 L0로 보존하고 L1 사실, L2 장면, L3 Persona 순서로 출처 관계를 만든다.
8. Persona는 서로 다른 L1 또는 L2 근거가 두 개 이상일 때만 만든다.

의미가 불명확한 문서를 추측으로 계약으로 승격하지 않는다. `draft`로 두고 판단 근거와 열린 질문을 보고한다.

## 6. 초기 검증과 색인

```powershell
$env:PYTHONUTF8='1'
python <skill-path>/scripts/validate_knowledge.py <repository-root>
```

PyYAML이 없으면 자동 설치하지 않는다. 사용자 승인을 받은 뒤 `python -m pip install -r <skill-path>/scripts/requirements.txt`를 실행한다.

임베딩이 활성화됐으면 provider 중립 청크 manifest와 로컬 SQLite BM25 위치 색인을 만든다.

```powershell
$env:PYTHONUTF8='1'
python <skill-path>/scripts/build_embedding_index.py <repository-root>
python <skill-path>/scripts/build_search_index.py <repository-root>
```

BM25는 관련 가능성이 있는 후보를 넓게 찾으며 `path`, `id`, `rank`, `via`, `engine`만 반환한다. 제목·요약·본문·snippet을 검색 결과에 싣지 않고, LLM이 `query read`로 원문을 선택해 읽는다.

오류 0건이 될 때까지 구축을 완료로 보고하지 않는다. 색인은 원본이 아니라 재생성 가능한 파생 데이터다. 조회 명령은 `lmwiki-steward/scripts/knowledge_cli.py query`를 사용한다. 관리 명령은 같은 CLI의 `manage` 아래에 있으며 변경 명령은 사용자 허락 후에만 `--apply`를 전달한다.

## 7. 완료와 인계

다음을 보고하고 이후 일상 관리는 `$lmwiki-steward`로 인계한다.

- 구축 모드와 생성·병합·이동한 파일
- 활성 계약과 아직 `draft`인 문서
- 임베딩 선택과 외부 전송 정책
- 기억 캡처 정책, L0–L3 수와 Persona 근거
- 기본 owner/team, grant와 로컬 전용 기억 경로
- 검증 오류·경고 수, 색인 청크 수와 BM25 문서 수
- 사람이 결정해야 하는 중복 원본이나 열린 질문

구축이 끝난 뒤 이 스킬로 일상 코드 변경을 관리하지 않는다.
