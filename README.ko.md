# TreeWiki

TreeWiki는 저장소 지도, 계약, 결정, runbook과 승인 기반 기억을 사람과 코딩 에이전트가 함께 유지하도록 돕는 Agent Skill입니다. 기준 호출은 `$treewiki`입니다.

## 릴리스와 호환성

첫 TreeWiki 릴리스는 **0.1.0**입니다. TreeWiki 이름, 읽기 전용 업그레이드 진단, 명시적 기억 공유 경계와 업그레이드 안내를 포함합니다. 기존 `LMWiki` 이름은 0.1.x에서만 기존 설치를 위한 호환 alias이며 shim은 **0.2.0**에서 제거합니다. 과거 ID와 provenance는 바꾸지 않습니다.

쓰기 전에 상태와 안내를 확인합니다.

```powershell
$env:PYTHONUTF8='1'
python skills/treewiki/scripts/knowledge_cli.py manage upgrade-status <repository-root> --principal user:<id> --team team:<id> --offline
```

진단은 config schema, 스킬 릴리스와 manifest/hash, vendored·전역 사본, hook 등록, migration, 색인, 호환 shim을 서로 구분합니다. 네트워크가 필요한 최신 릴리스는 opt-in이며 확인하지 못하면 추측하지 않고 `unknown`으로 표시합니다. `--apply`는 사용자 승인 뒤에만 사용하며, 레거시 파일을 자동 삭제하지 않습니다.

## 설치와 사용

```powershell
npx skills add j-token/treewiki --skill treewiki
```

저장소 작업에 `$treewiki`를 사용합니다. 적용 지도·계약을 읽고 ACL을 먼저 적용한 검색 뒤 원문을 직접 읽으며 변경을 검증합니다. 이름 영향, 계약 조사, 검색·검증처럼 독립적인 조사 흐름은 하위 에이전트로 나눌 수 있지만, 루트 에이전트가 ACL·근거·결과를 최종 검토합니다.

## 기억과 공유

| 계층 | 역할 | 위치 | Git 정책 |
| --- | --- | --- | --- |
| L0 | 대화·도구 실행 원문 근거 | `.knowledge/private-memory/l0/` | 로컬·ignore |
| L1 | 원자적 사실·선호·제약·사건 | 승인 뒤 `docs/memory/l1/` | 공유·추적 |
| L2 | 재사용할 프로젝트·작업 맥락 | 승인 뒤 `docs/memory/l2/` | 공유·추적 |
| L3 | 장기 팀 규칙 또는 Persona | 승인 뒤 `docs/memory/l3/` | 공유·추적 |

기억 저장 기본값은 `explicit`입니다. Stop hook은 기억을 저장하지 않습니다. 작업 완료 후보일 때 저장 여부를 묻고, 다음 메시지의 독립된 짧은 확인 뒤에만 L0 저장과 L1–L3 후보 처리를 시작합니다. 공유 문서는 작성자·승인자·불투명 source reference/hash·source-machine 식별자·상태를 가져야 합니다. Git 추적은 자동 stage·commit·push가 아닙니다.

TreeWiki는 같은 `(subject, scope, claim_key, claim_value)`를 지지하는 서로 다른 최상위 provenance와 work unit이 둘 이상이면 L3 후보를 적극적으로 한 번 제안합니다. 근거가 하나면 부족한 수를 알리고, 무관하거나 충돌하는 주장을 합치지 않으며, L3 최초 상태는 `proposed`입니다. 명시적 사용자 또는 팀 관리자 승인 뒤에만 `active`가 됩니다.

## 문서 모델과 검증

TreeWiki의 Markdown 유형은 `map`, `contract`, `decision`, `runbook`, `concept`, `reference`, `memory`, `persona`입니다. `AGENTS.md`는 적용 영역을 계약과 검증 진입점에 연결합니다. Markdown/frontmatter가 원본이고 색인은 재생성 가능한 파생물입니다.

```powershell
$env:PYTHONUTF8='1'
python skills/treewiki/scripts/knowledge_cli.py query search <repository-root> "인증" --principal user:owner --team team:product
python skills/treewiki/scripts/knowledge_cli.py query preferences <repository-root> --principal user:owner --team team:product
python skills/treewiki/scripts/knowledge_cli.py query l3-candidates <repository-root> --principal user:owner --team team:product
python skills/treewiki/scripts/knowledge_cli.py manage validate <repository-root>
```

최초 구축 때만 로컬 임베딩과 SQLite BM25 사용 여부를 묻습니다. 명시적 허락 없이는 문서를 외부로 보내지 않습니다.

## 업그레이드 순서

1. `upgrade-status`와 생성된 가이드에서 원인을 확인합니다.
2. migration dry run으로 config·스킬 사본·hook·색인 변경을 분리해 검토합니다.
3. 백업 또는 Git 상태를 확인한 뒤 필요한 `--apply`만 승인합니다.
4. `manage validate`를 실행하고 필요한 파생 색인만 재생성합니다.
5. TreeWiki 설치와 회귀 검증 후에만 호환 shim을 제거합니다. 캐시는 안내가 재생성 가능으로 분류한 경우에만 지우고, worktree는 디렉터리를 지우지 말고 `git worktree remove`를 사용합니다.
