# TreeWiki

TreeWiki는 저장소 지도, 계약, 결정, runbook, 문서 이력과 승인 기반 기억을 사람과 코딩 에이전트가 함께 유지하도록 돕습니다. 0.2.1은 하나의 Python 코어에 Agent Plugin, Codex, Claude Code 어댑터를 얇게 연결합니다.

## 릴리스와 호환성

현재 TreeWiki 릴리스는 **0.2.1**입니다. `LMWiki` 호환 shim은 제거했지만 과거 ID와 provenance는 바꾸지 않습니다. config v4와 memory layout v2는 유형화된 L3 knowledge/persona 경로와 안정 ID 문서 이력을 추가합니다.

쓰기 전에 상태와 안내를 확인합니다.

```powershell
$env:PYTHONUTF8='1'
python skills/treewiki/scripts/knowledge_cli.py manage upgrade-status <repository-root> --principal user:<id> --team team:<id> --offline
```

진단은 runtime, config, 문서 이력, memory layout, 색인, 어댑터, Claude alias와 hook 상태를 구분합니다. 최신 릴리스를 확인하지 못하면 추측하지 않고 `unknown`으로 표시합니다. 업그레이드는 기본 dry-run이고 정확한 plan ID가 있어야 apply됩니다.

## 설치와 사용

CLI 중심으로 쓸 때는 독립 Codex 스킬도 설치할 수 있습니다.

```powershell
npx skills add j-token/treewiki --skill treewiki
```

저장소 작업에 `$treewiki`를 사용합니다. 적용 지도·계약을 읽고 ACL을 먼저 적용한 검색 뒤 원문을 직접 읽으며 변경을 검증합니다. 이름 영향, 계약 조사, 검색·검증처럼 독립적인 조사 흐름은 하위 에이전트로 나눌 수 있지만, 루트 에이전트가 ACL·근거·결과를 최종 검토합니다.

## 플러그인 설치

### Claude Code

Claude Code 안에서 TreeWiki marketplace를 추가하고 플러그인을 설치합니다.

```text
/plugin marketplace add j-token/treewiki
/plugin install treewiki@treewiki-marketplace
```

플러그인의 이름공간 진입점은 `/treewiki:route`입니다. 정확한 `/treewiki` standalone 진입점을 추가하려면 TreeWiki checkout에서 alias 설치기를 실행합니다. 기본 실행은 dry-run이므로 `user` 또는 `project` 범위를 고른 뒤 출력된 plan ID를 확인하고 같은 ID로 적용합니다.

```powershell
$env:PYTHONUTF8='1'
python skills/treewiki/scripts/knowledge_cli.py manage setup-claude-alias <repository-root> --scope user --plugin-root plugins/treewiki-claude --principal user:<id>
python skills/treewiki/scripts/knowledge_cli.py manage setup-claude-alias <repository-root> --scope user --plugin-root plugins/treewiki-claude --plan-id <PLAN_ID> --apply --principal user:<id>
```

설치 후에는 명령 하나만 사용합니다.

```text
/treewiki [자연어 요청]
```

저장소 전용 alias는 `--scope project`를 사용합니다. 두 범위가 함께 있으면 `ALIAS_SHADOWED`를 경고하고 어느 쪽도 자동 삭제하지 않습니다.

### Codex / Agent Plugin

기본 설치 경로는 버전이 고정된 GitHub marketplace 플러그인입니다. 본체는 [Agent Plugins 1.0.0](https://agent-plugins.org/specification)을 따르고 Codex 메타데이터는 같은 portable 패키지를 연결하는 호환 어댑터입니다.

```powershell
codex plugin marketplace add j-token/treewiki --ref v0.2.1
codex plugin add treewiki@treewiki-marketplace
```

새 Codex 작업에서 현재 저장소의 TreeWiki 상태를 확인해 달라고 요청합니다. Codex는 자체 MCP 도구·결과·승인 UI를 사용해 binding, Overview, ACL Search, 문서 History, knowledge/persona L3 후보와 업그레이드 계획을 보여줍니다. binding 변경, L3 결정, 저장소 로컬 업그레이드는 먼저 dry-run 계획만 만들고 정확한 plan ID와 digest에 대한 명시적 승인 뒤에만 적용합니다. 전역 스킬·hook과 승인형 기억 업그레이드는 채팅으로 안내합니다.

추적되는 stdio MCP, Python 코어, PyYAML과 스킬에는 설치 후 `npm install`이나 `pip install`이 필요하지 않습니다. 저장소 도구는 승인된 `bindingId`만 받아 매 호출에서 저장소나 ACL identity가 바뀌는 일을 막습니다. 자세한 구조는 [`plugins/treewiki/README.md`](plugins/treewiki/README.md)에 있습니다.

선택적 HTTP transport도 커스텀 App 리소스 없이 같은 일반 MCP 도구를 제공합니다. 터널과 Developer mode는 Codex 설치 절차가 아니며 [`docs/chatgpt-http-development.md`](docs/chatgpt-http-development.md)에 별도로 설명합니다.

## 기억과 공유

| 계층 | 역할 | 위치 | Git 정책 |
| --- | --- | --- | --- |
| L0 | 대화·도구 실행 원문 근거 | `.knowledge/private-memory/l0/` | 로컬·ignore |
| L1 | 원자적 사실·선호·제약·사건 | 승인 뒤 `docs/memory/l1/` | 공유·추적 |
| L2 | 재사용할 프로젝트·작업 맥락 | 승인 뒤 `docs/memory/l2/` | 공유·추적 |
| L3 knowledge | 장기 사실·정보 종합·규칙 | 승인 뒤 `docs/memory/l3/knowledge/` | 공유·추적 |
| L3 persona | 장기 사용자 선호 | 승인 뒤 `docs/memory/l3/persona/` | 공유·추적 |

기억 저장 기본값은 `explicit`입니다. Stop hook은 기억을 저장하지 않습니다. 작업 완료 후보일 때 저장 여부를 묻고, 다음 메시지의 독립된 짧은 확인 뒤에만 L0 저장과 L1–L3 후보 처리를 시작합니다. 공유 문서는 작성자·승인자·불투명 source reference/hash·source-machine 식별자·상태를 가져야 합니다. Git 추적은 자동 stage·commit·push가 아닙니다.

TreeWiki는 정확히 같은 주장뿐 아니라 여러 관찰이 같은 상위 결론을 지지하는 convergent evidence도 검사합니다. fact는 권위 출처 하나 또는 독립 출처 둘, information은 수렴 관찰 둘, rule은 공식·명시 선언 하나 또는 반복 결과 둘, preference는 명시적 사용자 선언 하나 또는 독립 작업의 동일 선택 둘과 확인이 필요합니다. 자동 처리는 `proposed`에서 멈추고, 새 후보 등록 성공 뒤에만 `L3_CANDIDATE_CREATED` notice를 한 번 출력합니다. 활성화·폐기·대체에는 별도 검토 plan ID가 필요합니다.

## 문서 모델과 검증

관리 문서는 `created_at`, `modified_at`, `verified_at`, `revision`, `history_ref`를 갖고 옆의 `<stable-id>.history.jsonl`에 의미 변경 이력을 기록합니다. 원출처 재검증은 `verified_at`만 바꾸며 semantic revision을 올리지 않습니다. Markdown/frontmatter와 ledger가 원본이고 색인은 재생성 가능한 파생물입니다.

OKF v0.2는 TreeWiki 네이티브 저장 스키마를 대체하지 않는 import/export 호환 계층입니다. export는 수명주기 시각, 검증 이벤트, 근거 출처와 상태를 매핑하고 TreeWiki 고유 메타데이터를 extension으로 보존합니다.

```powershell
$env:PYTHONUTF8='1'
python skills/treewiki/scripts/knowledge_cli.py query search <repository-root> "인증" --principal user:owner --team team:product
python skills/treewiki/scripts/knowledge_cli.py query preferences <repository-root> --principal user:owner --team team:product
python skills/treewiki/scripts/knowledge_cli.py query l3-candidates <repository-root> --principal user:owner --team team:product
python skills/treewiki/scripts/knowledge_cli.py query history <repository-root> --id DOC-ID --principal user:owner --team team:product
python skills/treewiki/scripts/knowledge_cli.py manage document-finalize <repository-root> --principal user:owner
python skills/treewiki/scripts/knowledge_cli.py manage document-move <repository-root> DOC-ID --to docs/new-path.md --principal user:owner
python skills/treewiki/scripts/knowledge_cli.py manage validate <repository-root>
```

최초 구축 때만 로컬 임베딩과 SQLite BM25 사용 여부를 묻습니다. 명시적 허락 없이는 문서를 외부로 보내지 않습니다.

## 업그레이드 순서

1. `upgrade-status`와 생성된 가이드에서 원인을 확인합니다.
2. migration dry run으로 config·스킬 사본·hook·색인 변경을 분리해 검토합니다.
3. 백업 또는 Git 상태를 확인한 뒤 필요한 `--apply`만 승인합니다.
4. `manage validate`를 실행하고 필요한 파생 색인만 재생성합니다.
5. TreeWiki 설치와 회귀 검증 후에만 호환 shim을 제거합니다. 캐시는 안내가 재생성 가능으로 분류한 경우에만 지우고, worktree는 디렉터리를 지우지 말고 `git worktree remove`를 사용합니다.
