# LMWiki Schema

- 권위 문서는 `map`, `contract`, `decision`, `runbook`, `concept`, `reference` 유형을 사용한다.
- 대화 기억은 `memory`, 장기 협업 Persona는 `persona` 유형을 사용한다.
- 기억은 `l0`, `l1`, `l2`, `l3` 계층과 `distilled_from` 출처 관계를 유지한다.
- L1은 `memory.kind`로 사실, 선호, 조건부 행동, 제약, 사건과 맥락을 구분한다.
- `memory.capture: explicit`은 LMWiki 스킬이 작업 완료 후보를 판단하고 사용자의 명시적인 저장 확인을 받은 다음 턴에서 L0–L2를 순차 처리한다.
- L3는 같은 파생 계보를 중복 계산하지 않고 서로 다른 최상위 provenance가 최소 두 개일 때만 발화한다.
- runbook은 완료·commit·push·pull request 같은 인수인계 경계 신호에서 같은 작업 단위에 한 번만 제안하며, 사용자가 `만들기`를 선택한 뒤에만 `draft`로 시작한다.
- 모든 기억 문서는 `access` 정책을 가진다.
- 개인·제한 기억은 Git 비추적 로컬 경로에 둔다.
- Markdown과 frontmatter가 원본이며 검색 색인은 재생성 가능한 파생물이다.
- `docs/vocabulary/glossary.yml`은 저장소 고유 명칭의 `term`과 `description`을 보관하는 권위 있는 원본이다.
- 관리 대상 지식 문서는 `glossary_terms`로 사용한 저장소 고유 용어를 선언하고 미등록 후보 검사를 통과한다.
