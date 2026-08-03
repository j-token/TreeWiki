---
name: lmwiki
description: AGENTS.md 지도, 유형화된 Markdown, L0–L3 기억과 Persona, 사용자·팀·역할·에이전트 ACL, SQLite BM25 위치 검색과 승인 기반 관리 명령으로 LMWiki를 구축하고 운영합니다. 최초 구축에서는 임베딩 사용 여부를 한 번 확인하고 저장합니다. 새 저장소 초기화, 기존 문서 이관, 코드·문서 변경, 감사, 기억 증류, 계약 생명주기, 조회, 동기화와 재색인에 사용합니다.
---

# LMWiki

한 스킬 안에서 저장소 상태와 요청에 맞는 모드를 고르고, 그 모드에 필요한 참고문서만 읽는다.

## 1. 상태와 모드 선택

루트 `AGENTS.md`, `.knowledge/config.yml`, Git 상태를 먼저 확인한다.

| 상태 또는 요청 | 모드 | 다음 읽기 |
| --- | --- | --- |
| 둘 다 없음 | `bootstrap` | [도입 절차](references/adoption-workflow.md) |
| 일부만 있거나 기존 문서 이관 | `adopt` 또는 `repair` | [도입 절차](references/adoption-workflow.md) |
| 코드·문서 변경 | `change` | [변경과 감사](references/change-and-audit.md) |
| 읽기·진단·오래된 지식 점검 | `audit` | [변경과 감사](references/change-and-audit.md) |
| 대화 기억·Persona 갱신 | `memory` | [기억과 Persona](references/memory-and-persona.md), [훅 생명주기](references/hook-lifecycle.md) |
| 파생 색인만 갱신 | `reindex` | [임베딩과 위치 검색](references/embedding-retrieval.md) |

`audit`에서는 파일을 수정하지 않는다. 구조가 없을 때만 `bootstrap`을 사용하며, 기존 파일을 덮어쓰지 않는다.

## 2. 최초 임베딩 선택

`bootstrap`, `adopt`, `repair` 모드에서 `.knowledge/config.yml`의 `embedding.enabled`가 명시적인 boolean인지 확인한다. 값이 없거나 유효하지 않을 때만, 파일을 만들거나 바꾸기 전에 다음 질문을 한 번 한다.

> 이 저장소의 LMWiki 문서 검색에 임베딩과 로컬 SQLite BM25 위치 색인을 사용하시겠습니까?

- 명시적인 예/아니요 답을 기다린다. 답하지 않았다고 비활성화로 간주하지 않는다.
- `예`: `embedding.enabled: true`, `embedding.execution: local`, `retrieval.bm25_enabled: true`를 저장한다. BM25는 임베딩 활성화 시 기본으로 켠다.
- `아니요`: `embedding.enabled: false`, `embedding.execution: none`을 저장한다.
- 원격 실행은 이 질문과 분리한다. 문서 외부 전송을 명시적으로 허용받기 전에는 `remote`를 선택하지 않는다.
- 이미 명시적인 선택이 저장돼 있으면 다시 묻지 않고 그 값을 사용한다. 이후 `change`, `audit`, `memory`, `reindex`에서도 재질문하지 않는다.

bootstrap 명령에는 답을 `--embedding local` 또는 `--embedding disabled`로 반드시 전달한다. 기존 설정에 선택만 빠진 경우에는 해당 값만 보완하며 다른 설정을 덮어쓰지 않는다.

## 3. 필요한 규칙만 공개

- 모든 조회·관리 명령: [명령 경계](references/command-boundaries.md)
- 사용자·팀·역할·에이전트 권한이 관련될 때: [접근 제어](references/access-control.md)
- `AGENTS.md`를 만들거나 바꿀 때: [지도 규칙](references/agents-map.md)
- Markdown frontmatter를 만들거나 바꿀 때: [메타데이터 스키마](references/metadata-schema.md)
- 계약·결정의 대체·폐기·복구가 필요할 때: [생명주기와 관계](references/lifecycle-and-relations.md)
- `.knowledge/config.yml`에서 `embedding.enabled: true`일 때만: [임베딩과 위치 검색](references/embedding-retrieval.md)
- L0–L3 자동 기억 또는 작업 완료 runbook이 관련될 때: [훅 생명주기](references/hook-lifecycle.md)

필요하지 않은 reference를 미리 읽지 않는다. reference는 이 파일에서 직접 연결된 1단계 깊이만 사용한다.

## 4. 공통 안전 경계

- Markdown과 frontmatter를 권위 있는 원본으로 유지한다.
- 조회 전에 호출자의 `user:*`, `team:*`, 선택적 `role:*`, `agent:*`를 확인하고 ACL을 점수 계산보다 먼저 적용한다.
- `query search`, `read`, `list`, `graph`와 `manage validate`는 읽기 전용이다.
- `manage sync`, `reindex`, `migrate`는 manager 주체가 사용자 허락을 받은 뒤에만 `--apply`를 사용한다.
- 기억 캡처 기본값은 `hook`이다. L0–L2는 Stop 훅이 순서대로 발화하고, 개인·제한 기억은 Git에서 제외된 `.knowledge/private-memory/`에 둔다.
- L3는 프로그램이 같은 subject의 활성 L1/L2 근거 수를 확인한 뒤에만 발화한다. runbook은 사용자 피드백이 필요하지 않은 완료 후보에서만 검토하며 새 문서는 `draft`로 시작한다.
- 외부 전송을 허용받지 않으면 로컬 처리만 사용하고, 확인되지 않은 provider나 model ID를 만들지 않는다.

## 5. 실행 진입점

Windows PowerShell에서는 UTF-8 모드와 `python`을 사용한다.

```powershell
$env:PYTHONUTF8='1'
python <skill-path>/scripts/bootstrap_lmwiki.py <repository-root> --embedding local --owner user:<id> --team team:<id>
python <skill-path>/scripts/knowledge_cli.py query search <repository-root> "<query>" --principal user:<id> --team team:<id>
python <skill-path>/scripts/knowledge_cli.py manage validate <repository-root>
```

검색은 문서 위치만 반환한다. 필요한 후보는 `query read`로 직접 연다. 구조 변경 후 검증 오류가 있으면 완료로 보고하지 않는다.
최초 질문의 답이 아니요이면 bootstrap 예시의 `local` 대신 `disabled`를 사용한다.

## 6. 완료 보고

- 선택한 모드와 변경한 경로
- 적용한 계약·결정·지도와 검증 근거
- 기억 계층, provenance와 접근 범위
- 실행한 검증과 오류·경고 수
- 임베딩 선택, BM25 문서 수와 외부 전송 정책
- 문서 영향이 없다면 그 근거
- 훅에서 발화한 L0–L3와 runbook 단계, 피드백 필요로 건너뛴 단계
